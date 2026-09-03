"""Integration of the XAAC Thin Client Debian package for phase 6.1."""
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


class XaacThinClientPackageError(RuntimeError):
    """Raised when the XAAC Thin Client package is invalid or unsafe."""


_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){2}(?:[+~.-][A-Za-z0-9.+~:-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise XaacThinClientPackageError(f"Ruta insegura: {name}")
    return path


def load_xaac_thin_client_package_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise XaacThinClientPackageError(f"No s'ha pogut carregar el perfil del paquet: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "package", "installation", "update"} or raw.get("schema_version") != 1:
        raise XaacThinClientPackageError("Esquema del paquet XAAC Thin Client invàlid")
    package = raw["package"]
    expected_package = {"name", "architecture", "version", "artifact", "sha256", "allow_newer_patch", "dependencies"}
    if not isinstance(package, dict) or set(package) != expected_package:
        raise XaacThinClientPackageError("Metadades del paquet incompletes")
    if package["name"] != "xaac-thinclient" or not _PACKAGE.fullmatch(str(package["name"])):
        raise XaacThinClientPackageError("Nom de paquet invàlid")
    if package["architecture"] != "all" or not _VERSION.fullmatch(str(package["version"])):
        raise XaacThinClientPackageError("Arquitectura o versió del paquet invàlida")
    artifact = Path(str(package["artifact"]))
    if artifact.is_absolute() or ".." in artifact.parts or artifact.suffix != ".deb":
        raise XaacThinClientPackageError("Ruta de l'artefacte .deb insegura")
    checksum = package["sha256"]
    if checksum is not None and not _SHA256.fullmatch(str(checksum)):
        raise XaacThinClientPackageError("SHA-256 del paquet invàlid")
    if not isinstance(package["allow_newer_patch"], bool) or not isinstance(package["dependencies"], list):
        raise XaacThinClientPackageError("Política de versió o dependències invàlida")
    if any(not _PACKAGE.fullmatch(str(item)) for item in package["dependencies"]):
        raise XaacThinClientPackageError("Dependència Debian invàlida")
    installation = raw["installation"]
    expected_installation = {"cache_path", "configuration_path", "apt_preferences_path", "install_recommends", "fail_on_downgrade"}
    if not isinstance(installation, dict) or set(installation) != expected_installation:
        raise XaacThinClientPackageError("Configuració d'instal·lació incompleta")
    for key in ("cache_path", "configuration_path", "apt_preferences_path"):
        _safe_absolute(installation[key], key)
    if installation["install_recommends"] is not False or installation["fail_on_downgrade"] is not True:
        raise XaacThinClientPackageError("La instal·lació ha de ser mínima i impedir downgrades")
    update = raw["update"]
    if not isinstance(update, dict) or set(update) != {"source", "channel", "package_hold", "verify_before_install"}:
        raise XaacThinClientPackageError("Política d'actualització incompleta")
    if update["source"] != "apt" or update["channel"] not in {"stable", "pilot", "development"} or update["verify_before_install"] is not True:
        raise XaacThinClientPackageError("Política d'actualització insegura")
    return raw


@dataclass(frozen=True, slots=True)
class DebianPackageMetadata:
    package: str
    version: str
    architecture: str
    dependencies: tuple[str, ...]
    sha256: str


MetadataRunner = Callable[..., subprocess.CompletedProcess[str]]


def inspect_debian_package(artifact: Path, *, runner: MetadataRunner = subprocess.run) -> DebianPackageMetadata:
    if not artifact.is_file() or artifact.is_symlink():
        raise XaacThinClientPackageError(f"No existeix un paquet .deb regular: {artifact}")
    try:
        result = runner(
            ("dpkg-deb", "--show", "--showformat=${Package}\n${Version}\n${Architecture}\n${Depends}\n", str(artifact)),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise XaacThinClientPackageError(f"No s'ha pogut inspeccionar el paquet Debian: {exc}") from exc
    lines = result.stdout.splitlines()
    if len(lines) < 3:
        raise XaacThinClientPackageError("Metadades dpkg-deb incompletes")
    dependencies = tuple(sorted({part.strip().split(" ")[0].split(":", 1)[0] for part in (lines[3] if len(lines) > 3 else "").split(",") if part.strip()}))
    return DebianPackageMetadata(lines[0], lines[1], lines[2], dependencies, hashlib.sha256(artifact.read_bytes()).hexdigest())


def _version_tuple(value: str) -> tuple[int, int, int]:
    base = value.split("-", 1)[0].split("+", 1)[0].split("~", 1)[0]
    try:
        major, minor, patch = base.split(".")[:3]
        return int(major), int(minor), int(patch)
    except (ValueError, IndexError) as exc:
        raise XaacThinClientPackageError(f"Versió no comparable: {value}") from exc


def validate_package_metadata(metadata: DebianPackageMetadata, profile: dict[str, Any]) -> None:
    package = profile["package"]
    if (metadata.package, metadata.architecture) != (package["name"], package["architecture"]):
        raise XaacThinClientPackageError("El nom o l'arquitectura del paquet no coincideixen")
    actual, expected = _version_tuple(metadata.version), _version_tuple(package["version"])
    valid_version = actual == expected or (package["allow_newer_patch"] and actual[:2] == expected[:2] and actual[2] >= expected[2])
    if not valid_version:
        raise XaacThinClientPackageError("La versió del paquet no compleix la política")
    checksum = package["sha256"]
    if checksum is not None and metadata.sha256 != checksum:
        raise XaacThinClientPackageError("El SHA-256 del paquet no coincideix")
    missing = sorted(set(package["dependencies"]) - set(metadata.dependencies))
    if missing:
        raise XaacThinClientPackageError("Falten dependències declarades al paquet: " + ", ".join(missing))


@dataclass(frozen=True, slots=True)
class XaacThinClientPackagePlan:
    rootfs: Path
    artifact: Path
    metadata: DebianPackageMetadata
    cache_path: PurePosixPath
    configuration_path: PurePosixPath
    apt_preferences_path: PurePosixPath
    channel: str

    def install_commands(self) -> tuple[tuple[str, ...], ...]:
        cache = str(self.cache_path)
        return (
            ("chroot", str(self.rootfs), "dpkg", "--install", cache),
            ("chroot", str(self.rootfs), "apt-get", "--fix-broken", "install", "--yes", "--no-install-recommends"),
        )

    def to_manifest(self) -> dict[str, object]:
        return {"package": self.metadata.package, "version": self.metadata.version, "architecture": self.metadata.architecture, "sha256": self.metadata.sha256, "dependencies": list(self.metadata.dependencies), "channel": self.channel, "cache_path": str(self.cache_path)}


def create_xaac_thin_client_package_plan(rootfs: Path, project_root: Path, profile_path: Path, *, runner: MetadataRunner = subprocess.run) -> XaacThinClientPackagePlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise XaacThinClientPackageError(f"Rootfs insegur: {root}")
    profile = load_xaac_thin_client_package_profile(profile_path)
    artifact = (project_root / profile["package"]["artifact"]).resolve()
    try:
        artifact.relative_to(project_root.resolve())
    except ValueError as exc:
        raise XaacThinClientPackageError("L'artefacte queda fora del projecte") from exc
    metadata = inspect_debian_package(artifact, runner=runner)
    validate_package_metadata(metadata, profile)
    installation = profile["installation"]
    return XaacThinClientPackagePlan(root, artifact, metadata, _safe_absolute(installation["cache_path"], "cache_path"), _safe_absolute(installation["configuration_path"], "configuration_path"), _safe_absolute(installation["apt_preferences_path"], "apt_preferences_path"), profile["update"]["channel"])


class XaacThinClientPackageInstaller:
    @staticmethod
    def _destination(rootfs: Path, path: PurePosixPath) -> Path:
        return rootfs / path.relative_to("/")

    def execute(self, plan: XaacThinClientPackagePlan, *, dry_run: bool = False, runner: MetadataRunner = subprocess.run) -> tuple[Path, ...]:
        if dry_run:
            return ()
        cache = self._destination(plan.rootfs, plan.cache_path)
        config = self._destination(plan.rootfs, plan.configuration_path)
        preferences = self._destination(plan.rootfs, plan.apt_preferences_path)
        for destination in (cache, config, preferences):
            if destination.is_symlink():
                raise XaacThinClientPackageError(f"No s'escriurà sobre un enllaç simbòlic: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(cache.suffix + ".tmp")
        shutil.copyfile(plan.artifact, temporary)
        temporary.chmod(0o644)
        temporary.replace(cache)
        config.write_text(json.dumps(plan.to_manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        config.chmod(0o640)
        preferences.write_text(f"Package: {plan.metadata.package}\nPin: release a={plan.channel}\nPin-Priority: 700\n", encoding="utf-8")
        preferences.chmod(0o644)
        for command in plan.install_commands():
            try:
                runner(command, check=True, text=True, capture_output=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                raise XaacThinClientPackageError(f"Ha fallat la instal·lació del paquet XAAC Thin Client: {exc}") from exc
        return cache, config, preferences
