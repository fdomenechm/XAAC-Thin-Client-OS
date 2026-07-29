"""Installation and initial system integration of XAAC Agent (phase 6.2)."""
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
    """Raised when the agent package/profile is invalid or unsafe."""


_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){2}(?:[+~.-][A-Za-z0-9.+~:-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ACCOUNT = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
Runner = Callable[..., subprocess.CompletedProcess[str]]


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
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "package", "installation", "service", "security"} or raw.get("schema_version") != 1:
        raise XaacAgentPackageError("Esquema del paquet XAAC Agent invàlid")
    package = raw["package"]
    if not isinstance(package, dict) or set(package) != {"name", "architecture", "version", "artifact", "sha256", "dependencies"}:
        raise XaacAgentPackageError("Metadades del paquet incompletes")
    if package["name"] != "xaac-agent" or not _NAME.fullmatch(str(package["name"])) or package["architecture"] != "amd64" or not _VERSION.fullmatch(str(package["version"])):
        raise XaacAgentPackageError("Nom, arquitectura o versió invàlids")
    artifact = Path(str(package["artifact"]))
    if artifact.is_absolute() or ".." in artifact.parts or artifact.suffix != ".deb":
        raise XaacAgentPackageError("Ruta de l'artefacte insegura")
    if package["sha256"] is not None and not _SHA256.fullmatch(str(package["sha256"])):
        raise XaacAgentPackageError("SHA-256 invàlid")
    if not isinstance(package["dependencies"], list) or any(not _NAME.fullmatch(str(x)) for x in package["dependencies"]):
        raise XaacAgentPackageError("Dependències invàlides")
    install = raw["installation"]
    if not isinstance(install, dict) or set(install) != {"cache_path", "configuration_path", "state_directory", "log_directory"}:
        raise XaacAgentPackageError("Configuració d'instal·lació incompleta")
    for key, value in install.items():
        _absolute(value, key)
    service = raw["service"]
    if not isinstance(service, dict) or set(service) != {"user", "group", "unit", "executable", "restart", "restart_sec", "enabled"}:
        raise XaacAgentPackageError("Configuració del servei incompleta")
    if any(not _SAFE_ACCOUNT.fullmatch(str(service[k])) for k in ("user", "group")) or not str(service["unit"]).endswith(".service"):
        raise XaacAgentPackageError("Usuari, grup o unitat invàlids")
    _absolute(service["executable"], "executable")
    if service["restart"] not in {"on-failure", "always"} or not isinstance(service["restart_sec"], int) or service["restart_sec"] < 1 or service["enabled"] is not True:
        raise XaacAgentPackageError("Política del servei insegura")
    security = raw["security"]
    if not isinstance(security, dict) or set(security) != {"shell", "home", "configuration_mode", "directory_mode"}:
        raise XaacAgentPackageError("Política de seguretat incompleta")
    if security["shell"] != "/usr/sbin/nologin" or security["home"] != str(install["state_directory"]) or security["configuration_mode"] != "0640" or security["directory_mode"] != "0750":
        raise XaacAgentPackageError("Política de permisos insegura")
    return raw


@dataclass(frozen=True, slots=True)
class AgentMetadata:
    package: str
    version: str
    architecture: str
    dependencies: tuple[str, ...]
    sha256: str


def inspect_agent_package(artifact: Path, *, runner: Runner = subprocess.run) -> AgentMetadata:
    if not artifact.is_file() or artifact.is_symlink():
        raise XaacAgentPackageError(f"No existeix un paquet .deb regular: {artifact}")
    try:
        result = runner(("dpkg-deb", "--show", "--showformat=${Package}\n${Version}\n${Architecture}\n${Depends}\n", str(artifact)), check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise XaacAgentPackageError(f"No s'ha pogut inspeccionar el paquet: {exc}") from exc
    lines = result.stdout.splitlines()
    if len(lines) < 3:
        raise XaacAgentPackageError("Metadades dpkg-deb incompletes")
    deps = tuple(sorted({part.strip().split(" ")[0] for part in (lines[3] if len(lines) > 3 else "").split(",") if part.strip()}))
    return AgentMetadata(lines[0], lines[1], lines[2], deps, hashlib.sha256(artifact.read_bytes()).hexdigest())


@dataclass(frozen=True, slots=True)
class XaacAgentPlan:
    rootfs: Path
    artifact: Path
    metadata: AgentMetadata
    profile: dict[str, Any]

    def manifest(self) -> dict[str, object]:
        service = self.profile["service"]
        return {"package": self.metadata.package, "version": self.metadata.version, "architecture": self.metadata.architecture, "sha256": self.metadata.sha256, "service": service["unit"], "user": service["user"]}


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
    if package["sha256"] and package["sha256"] != metadata.sha256:
        raise XaacAgentPackageError("El SHA-256 no coincideix")
    missing = sorted(set(package["dependencies"]) - set(metadata.dependencies))
    if missing:
        raise XaacAgentPackageError("Falten dependències: " + ", ".join(missing))
    return XaacAgentPlan(root, artifact, metadata, profile)


class XaacAgentInstaller:
    def execute(self, plan: XaacAgentPlan, *, dry_run: bool = False, runner: Runner = subprocess.run) -> tuple[Path, ...]:
        if dry_run:
            return ()
        p, root = plan.profile, plan.rootfs
        install, service, security = p["installation"], p["service"], p["security"]
        cache = root / _absolute(install["cache_path"], "cache_path").relative_to("/")
        config = root / _absolute(install["configuration_path"], "configuration_path").relative_to("/")
        state = root / _absolute(install["state_directory"], "state_directory").relative_to("/")
        logs = root / _absolute(install["log_directory"], "log_directory").relative_to("/")
        unit = root / "etc/systemd/system" / service["unit"]
        for path in (cache, config, state, logs, unit):
            if path.is_symlink():
                raise XaacAgentPackageError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        for directory in (cache.parent, config.parent, state, logs, unit.parent):
            directory.mkdir(parents=True, exist_ok=True)
        state.chmod(int(security["directory_mode"], 8)); logs.chmod(int(security["directory_mode"], 8))
        tmp = cache.with_suffix(".deb.tmp"); shutil.copyfile(plan.artifact, tmp); tmp.chmod(0o644); tmp.replace(cache)
        config.write_text(yaml.safe_dump({"schema_version": 1, "agent": {"state_directory": str(install["state_directory"]), "log_directory": str(install["log_directory"]), "managed": True}}, sort_keys=False), encoding="utf-8")
        config.chmod(int(security["configuration_mode"], 8))
        unit.write_text("[Unit]\nDescription=XAAC Thin Client Agent\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\nUser={user}\nGroup={group}\nExecStart={exe} --config {cfg}\nRestart={restart}\nRestartSec={delay}\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\nProtectHome=true\nReadWritePaths={state} {logs}\n\n[Install]\nWantedBy=multi-user.target\n".format(user=service["user"], group=service["group"], exe=service["executable"], cfg=install["configuration_path"], restart=service["restart"], delay=service["restart_sec"], state=install["state_directory"], logs=install["log_directory"]), encoding="utf-8")
        unit.chmod(0o644)
        try:
            group_probe = runner(("chroot", str(root), "getent", "group", service["group"]), check=False, text=True, capture_output=True)
            if group_probe.returncode != 0:
                runner(("chroot", str(root), "groupadd", "--system", service["group"]), check=True, text=True, capture_output=True)
            user_probe = runner(("chroot", str(root), "id", "--user", service["user"]), check=False, text=True, capture_output=True)
            if user_probe.returncode != 0:
                runner(("chroot", str(root), "useradd", "--system", "--gid", service["group"], "--home-dir", security["home"], "--shell", security["shell"], service["user"]), check=True, text=True, capture_output=True)
            for command in (
                ("chroot", str(root), "dpkg", "--install", str(install["cache_path"])),
                ("chroot", str(root), "apt-get", "--fix-broken", "install", "--yes", "--no-install-recommends"),
                ("chroot", str(root), "chown", "-R", f"{service['user']}:{service['group']}", str(install["state_directory"]), str(install["log_directory"])),
                ("chroot", str(root), "systemctl", "enable", service["unit"]),
            ):
                runner(command, check=True, text=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise XaacAgentPackageError(f"Ha fallat la integració de XAAC Agent: {exc}") from exc
        manifest = config.parent / "package.json"
        manifest.write_text(json.dumps(plan.manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8"); manifest.chmod(0o640)
        return cache, config, state, logs, unit, manifest
