"""Validation and installation of the packaged XAAC Agent (Block 7.1).

XAAC Thin Client OS deliberately does not recreate the agent account,
configuration or systemd units. Those resources belong to the xaac-agent
Debian package and are only verified here after installation.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class XaacAgentPackageError(RuntimeError):
    """Raised when the packaged agent is missing, inconsistent or unsafe."""


_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){2}(?:[+~.-][A-Za-z0-9.+~:-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ACCOUNT = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
Runner = Callable[..., subprocess.CompletedProcess[str]]
_MIN_DEB_SIZE = 1024
_DEB_MAGIC = b"!<arch>\n"


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise XaacAgentPackageError(f"Ruta insegura: {field}")
    return path


def load_xaac_agent_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise XaacAgentPackageError(f"No s'ha pogut carregar el perfil de l'Agent: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "package", "installation", "ownership"} or raw.get("schema_version") != 3:
        raise XaacAgentPackageError("Esquema del paquet XAAC Agent invàlid")

    package = raw["package"]
    expected_package = {"name", "architecture", "application_version", "version", "artifact", "sha256", "dependencies"}
    if not isinstance(package, dict) or set(package) != expected_package:
        raise XaacAgentPackageError("Metadades del paquet incompletes")
    if package["name"] != "xaac-agent" or not _NAME.fullmatch(str(package["name"])):
        raise XaacAgentPackageError("Nom del paquet invàlid")
    if package["architecture"] != "amd64":
        raise XaacAgentPackageError("Arquitectura del paquet invàlida")
    if not _VERSION.fullmatch(str(package["application_version"])) or not _VERSION.fullmatch(str(package["version"])):
        raise XaacAgentPackageError("Versió del paquet invàlida")
    if not str(package["version"]).startswith(f"{package['application_version']}-"):
        raise XaacAgentPackageError("La versió Debian no correspon a la versió de l'aplicació")
    artifact = Path(str(package["artifact"]))
    if artifact.is_absolute() or ".." in artifact.parts or artifact.suffix != ".deb":
        raise XaacAgentPackageError("Ruta de l'artefacte insegura")
    if not _SHA256.fullmatch(str(package["sha256"])):
        raise XaacAgentPackageError("SHA-256 obligatori o invàlid")
    if not isinstance(package["dependencies"], list) or any(not _NAME.fullmatch(str(x)) for x in package["dependencies"]):
        raise XaacAgentPackageError("Dependències invàlides")

    installation = raw["installation"]
    expected_installation = {"cache_path", "manifest_path", "install_recommends", "required_paths"}
    if not isinstance(installation, dict) or set(installation) != expected_installation:
        raise XaacAgentPackageError("Configuració d'instal·lació incompleta")
    _absolute(installation["cache_path"], "cache_path")
    _absolute(installation["manifest_path"], "manifest_path")
    if installation["install_recommends"] is not False:
        raise XaacAgentPackageError("XAAC Agent s'ha d'instal·lar sense paquets recomanats")
    required_paths = installation["required_paths"]
    if not isinstance(required_paths, list) or not required_paths:
        raise XaacAgentPackageError("Cal declarar els fitxers obligatoris del paquet")
    for index, value in enumerate(required_paths):
        _absolute(value, f"required_paths[{index}]")

    ownership = raw["ownership"]
    expected_ownership = {"user", "group", "configuration_root", "runtime_root", "state_root", "service_unit", "helper_socket", "command_group", "ipc_group", "runtime_directory", "helper_socket_path"}
    if not isinstance(ownership, dict) or set(ownership) != expected_ownership:
        raise XaacAgentPackageError("Contracte de propietat del paquet incomplet")
    if any(not _SAFE_ACCOUNT.fullmatch(str(ownership[key])) for key in ("user", "group", "command_group", "ipc_group")):
        raise XaacAgentPackageError("Usuari o grup de l'Agent invàlid")
    if ownership["command_group"] != "xaac-command" or ownership["ipc_group"] != "xaac-ipc":
        raise XaacAgentPackageError("Grups d'integració de l'Agent inesperats")
    for key in ("configuration_root", "runtime_root", "state_root", "runtime_directory", "helper_socket_path"):
        _absolute(ownership[key], key)
    if ownership["service_unit"] != "xaac-agent.service" or ownership["helper_socket"] != "xaac-privileged-helper.socket":
        raise XaacAgentPackageError("Unitats systemd de l'Agent inesperades")
    return raw


@dataclass(frozen=True, slots=True)
class AgentMetadata:
    package: str
    version: str
    architecture: str
    dependencies: tuple[str, ...]
    sha256: str
    size: int


def _dependency_names(value: str) -> tuple[str, ...]:
    result: set[str] = set()
    for group in value.split(","):
        for alternative in group.split("|"):
            token = alternative.strip().split(" ", 1)[0].split(":", 1)[0]
            if token and _NAME.fullmatch(token):
                result.add(token)
    return tuple(sorted(result))


def inspect_agent_package(artifact: Path, *, runner: Runner = subprocess.run) -> AgentMetadata:
    if not artifact.is_file() or artifact.is_symlink():
        raise XaacAgentPackageError(f"No existeix un paquet .deb regular: {artifact}")
    try:
        stat = artifact.stat()
        with artifact.open("rb") as handle:
            magic = handle.read(len(_DEB_MAGIC))
    except OSError as exc:
        raise XaacAgentPackageError(f"No s'ha pogut llegir el paquet: {exc}") from exc
    if stat.st_size < _MIN_DEB_SIZE or magic != _DEB_MAGIC:
        raise XaacAgentPackageError("L'artefacte XAAC Agent no és un paquet Debian real; possible placeholder")
    try:
        result = runner(
            ("dpkg-deb", "--show", "--showformat=${Package}\n${Version}\n${Architecture}\n${Depends}\n", str(artifact)),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise XaacAgentPackageError(f"No s'ha pogut inspeccionar el paquet: {exc}") from exc
    lines = result.stdout.splitlines()
    if len(lines) < 3:
        raise XaacAgentPackageError("Metadades dpkg-deb incompletes")
    return AgentMetadata(
        package=lines[0],
        version=lines[1],
        architecture=lines[2],
        dependencies=_dependency_names(lines[3] if len(lines) > 3 else ""),
        sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        size=stat.st_size,
    )


@dataclass(frozen=True, slots=True)
class XaacAgentPlan:
    rootfs: Path
    artifact: Path
    metadata: AgentMetadata
    profile: dict[str, Any]

    @property
    def cache_path(self) -> PurePosixPath:
        return _absolute(self.profile["installation"]["cache_path"], "cache_path")

    @property
    def manifest_path(self) -> PurePosixPath:
        return _absolute(self.profile["installation"]["manifest_path"], "manifest_path")

    def install_command(self) -> tuple[str, ...]:
        return (
            "chroot", str(self.rootfs), "apt-get", "install", "--yes", "--no-install-recommends", str(self.cache_path)
        )

    def verification_command(self) -> tuple[str, ...]:
        required = " ".join(f"test -e {path};" for path in self.profile["installation"]["required_paths"])
        ownership = self.profile["ownership"]
        command = (
            f"test \"$(dpkg-query -W -f='${{Status}}' {self.metadata.package})\" = 'install ok installed'; "
            f"test \"$(dpkg-query -W -f='${{Version}}' {self.metadata.package})\" = '{self.metadata.version}'; "
            f"getent passwd {ownership['user']} >/dev/null; getent group {ownership['group']} >/dev/null; "
            f"getent group {ownership['command_group']} >/dev/null; getent group {ownership['ipc_group']} >/dev/null; "
            f"id -nG {ownership['user']} | tr ' ' '\\n' | grep -Fx {ownership['command_group']} >/dev/null; "
            f"id -nG {ownership['user']} | tr ' ' '\\n' | grep -Fx {ownership['ipc_group']} >/dev/null; "
            f"grep -F 'd /run/xaac-agent 0750 root xaac-command -' /usr/lib/tmpfiles.d/xaac-agent.conf >/dev/null; "
            f"grep -F 'd {ownership['runtime_directory']} 0700 xaac-agent xaac-agent -' /usr/lib/tmpfiles.d/xaac-agent.conf >/dev/null; "
            f"{required} "
            f"systemctl is-enabled {ownership['service_unit']} >/dev/null; "
            f"systemctl is-enabled {ownership['helper_socket']} >/dev/null"
        )
        return ("chroot", str(self.rootfs), "/bin/sh", "-ec", command)

    def manifest(self) -> dict[str, object]:
        return {
            "package": self.metadata.package,
            "application_version": self.profile["package"]["application_version"],
            "debian_version": self.metadata.version,
            "architecture": self.metadata.architecture,
            "sha256": self.metadata.sha256,
            "size": self.metadata.size,
            "dependencies": list(self.metadata.dependencies),
            "managed_by": "xaac-agent.deb",
        }


def create_xaac_agent_plan(rootfs: Path, project_root: Path, profile_path: Path, *, runner: Runner = subprocess.run) -> XaacAgentPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise XaacAgentPackageError(f"Rootfs insegur: {root}")
    profile = load_xaac_agent_profile(profile_path)
    artifact = (project_root / profile["package"]["artifact"]).resolve()
    try:
        artifact.relative_to(project_root.resolve())
    except ValueError as exc:
        raise XaacAgentPackageError("L'artefacte queda fora del projecte") from exc
    metadata = inspect_agent_package(artifact, runner=runner)
    package = profile["package"]
    if (metadata.package, metadata.architecture, metadata.version) != (package["name"], package["architecture"], package["version"]):
        raise XaacAgentPackageError("Les metadades del paquet no coincideixen")
    if package["sha256"] != metadata.sha256:
        raise XaacAgentPackageError("El SHA-256 no coincideix")
    missing = sorted(set(package["dependencies"]) - set(metadata.dependencies))
    if missing:
        raise XaacAgentPackageError("Falten dependències: " + ", ".join(missing))
    return XaacAgentPlan(root, artifact, metadata, profile)


class XaacAgentInstaller:
    @staticmethod
    def _destination(rootfs: Path, path: PurePosixPath) -> Path:
        return rootfs / path.relative_to("/")

    def execute(self, plan: XaacAgentPlan, *, dry_run: bool = False, runner: Runner = subprocess.run) -> tuple[Path, ...]:
        if dry_run:
            return ()
        cache = self._destination(plan.rootfs, plan.cache_path)
        manifest = self._destination(plan.rootfs, plan.manifest_path)
        for destination in (cache, manifest):
            if destination.is_symlink():
                raise XaacAgentPackageError(f"No s'escriurà sobre un enllaç simbòlic: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(cache.suffix + ".tmp")
        shutil.copyfile(plan.artifact, temporary)
        temporary.chmod(0o644)
        temporary.replace(cache)
        try:
            runner(plan.install_command(), check=True, text=True, capture_output=True)
            runner(plan.verification_command(), check=True, text=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise XaacAgentPackageError(f"Ha fallat la instal·lació o verificació de XAAC Agent: {exc}") from exc
        manifest.write_text(json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest.chmod(0o640)
        return cache, manifest
