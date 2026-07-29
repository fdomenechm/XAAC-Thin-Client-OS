"""Controlled RustDesk Debian package integration for phase 8.1."""
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


class RustDeskPackageError(RuntimeError):
    """Raised when the controlled RustDesk package definition is invalid."""


_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){2}(?:[+~.-][A-Za-z0-9.+~:-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise RustDeskPackageError(f"Ruta insegura: {field}")
    return path


def load_rustdesk_package_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RustDeskPackageError(f"No s'ha pogut carregar el perfil RustDesk: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "origin", "package", "installation", "removal"} or raw.get("schema_version") != 1:
        raise RustDeskPackageError("Esquema del paquet RustDesk invàlid")
    origin = raw["origin"]
    if not isinstance(origin, dict) or set(origin) != {"type", "vendor", "project", "license", "source_url"}:
        raise RustDeskPackageError("Origen RustDesk incomplet")
    if origin["type"] != "bundled-deb" or origin["vendor"] != "XAAC" or origin["project"] != "RustDesk":
        raise RustDeskPackageError("Origen RustDesk no controlat")
    if origin["license"] != "AGPL-3.0" or not isinstance(origin["source_url"], str) or not origin["source_url"].startswith("https://"):
        raise RustDeskPackageError("Llicència o URL d'origen invàlida")
    package = raw["package"]
    expected = {"name", "upstream_name", "version", "architecture", "artifact", "sha256", "dependencies"}
    if not isinstance(package, dict) or set(package) != expected:
        raise RustDeskPackageError("Metadades RustDesk incompletes")
    if package["name"] != "rustdesk-xaac" or package["upstream_name"] != "rustdesk":
        raise RustDeskPackageError("Nom del paquet RustDesk invàlid")
    if not _NAME.fullmatch(package["name"]) or not _VERSION.fullmatch(str(package["version"])) or package["architecture"] != "amd64":
        raise RustDeskPackageError("Versió o arquitectura RustDesk invàlida")
    artifact = Path(str(package["artifact"]))
    if artifact.is_absolute() or ".." in artifact.parts or artifact.suffix != ".deb":
        raise RustDeskPackageError("Ruta de l'artefacte RustDesk insegura")
    if package["sha256"] is not None and not _SHA256.fullmatch(str(package["sha256"])):
        raise RustDeskPackageError("SHA-256 RustDesk invàlid")
    if not isinstance(package["dependencies"], list) or any(not _NAME.fullmatch(str(item)) for item in package["dependencies"]):
        raise RustDeskPackageError("Dependències RustDesk invàlides")
    installation = raw["installation"]
    if not isinstance(installation, dict) or set(installation) != {"cache_path", "manifest_path", "install_recommends", "verify_metadata"}:
        raise RustDeskPackageError("Configuració d'instal·lació RustDesk incompleta")
    _absolute(installation["cache_path"], "cache_path")
    _absolute(installation["manifest_path"], "manifest_path")
    if installation["install_recommends"] is not False or installation["verify_metadata"] is not True:
        raise RustDeskPackageError("Política d'instal·lació RustDesk insegura")
    removal = raw["removal"]
    if not isinstance(removal, dict) or set(removal) != {"purge", "autoremove", "remove_cache", "remove_manifest"}:
        raise RustDeskPackageError("Política de desinstal·lació RustDesk incompleta")
    if removal != {"purge": True, "autoremove": True, "remove_cache": True, "remove_manifest": True}:
        raise RustDeskPackageError("La desinstal·lació RustDesk ha de ser completa")
    return raw


@dataclass(frozen=True, slots=True)
class RustDeskDebMetadata:
    package: str
    version: str
    architecture: str
    dependencies: tuple[str, ...]
    sha256: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


def inspect_rustdesk_deb(artifact: Path, *, runner: Runner = subprocess.run) -> RustDeskDebMetadata:
    if not artifact.is_file() or artifact.is_symlink():
        raise RustDeskPackageError(f"No existeix un paquet RustDesk regular: {artifact}")
    try:
        result = runner(("dpkg-deb", "--show", "--showformat=${Package}\n${Version}\n${Architecture}\n${Depends}\n", str(artifact)), check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RustDeskPackageError(f"No s'ha pogut inspeccionar RustDesk: {exc}") from exc
    lines = result.stdout.splitlines()
    if len(lines) < 3:
        raise RustDeskPackageError("Metadades RustDesk incompletes")
    dependencies = tuple(sorted({part.strip().split(" ")[0] for part in (lines[3] if len(lines) > 3 else "").split(",") if part.strip()}))
    return RustDeskDebMetadata(lines[0], lines[1], lines[2], dependencies, hashlib.sha256(artifact.read_bytes()).hexdigest())


def validate_rustdesk_metadata(metadata: RustDeskDebMetadata, profile: dict[str, Any]) -> None:
    package = profile["package"]
    if (metadata.package, metadata.version, metadata.architecture) != (package["name"], package["version"], package["architecture"]):
        raise RustDeskPackageError("Les metadades del paquet RustDesk no coincideixen")
    if package["sha256"] is not None and metadata.sha256 != package["sha256"]:
        raise RustDeskPackageError("El SHA-256 RustDesk no coincideix")
    missing = sorted(set(package["dependencies"]) - set(metadata.dependencies))
    if missing:
        raise RustDeskPackageError("Falten dependències RustDesk: " + ", ".join(missing))


@dataclass(frozen=True, slots=True)
class RustDeskPackagePlan:
    rootfs: Path
    artifact: Path
    metadata: RustDeskDebMetadata
    cache_path: PurePosixPath
    manifest_path: PurePosixPath
    source_url: str

    def install_commands(self) -> tuple[tuple[str, ...], ...]:
        return (("chroot", str(self.rootfs), "dpkg", "--install", str(self.cache_path)), ("chroot", str(self.rootfs), "apt-get", "--fix-broken", "install", "--yes", "--no-install-recommends"))

    def uninstall_commands(self) -> tuple[tuple[str, ...], ...]:
        return (("chroot", str(self.rootfs), "apt-get", "purge", "--yes", self.metadata.package), ("chroot", str(self.rootfs), "apt-get", "autoremove", "--yes"))

    def manifest(self) -> dict[str, object]:
        return {"package": self.metadata.package, "version": self.metadata.version, "architecture": self.metadata.architecture, "dependencies": list(self.metadata.dependencies), "sha256": self.metadata.sha256, "origin": self.source_url, "artifact": str(self.artifact)}


def create_rustdesk_package_plan(rootfs: Path, project_root: Path, profile_path: Path, *, runner: Runner = subprocess.run) -> RustDeskPackagePlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise RustDeskPackageError(f"Rootfs insegur: {root}")
    profile = load_rustdesk_package_profile(profile_path)
    artifact = (project_root / profile["package"]["artifact"]).resolve()
    try:
        artifact.relative_to(project_root.resolve())
    except ValueError as exc:
        raise RustDeskPackageError("L'artefacte RustDesk queda fora del projecte") from exc
    metadata = inspect_rustdesk_deb(artifact, runner=runner)
    validate_rustdesk_metadata(metadata, profile)
    installation = profile["installation"]
    return RustDeskPackagePlan(root, artifact, metadata, _absolute(installation["cache_path"], "cache_path"), _absolute(installation["manifest_path"], "manifest_path"), profile["origin"]["source_url"])


class RustDeskPackageManager:
    @staticmethod
    def _target(rootfs: Path, path: PurePosixPath) -> Path:
        return rootfs / path.relative_to("/")

    def install(self, plan: RustDeskPackagePlan, *, dry_run: bool = False, runner: Runner = subprocess.run) -> tuple[Path, ...]:
        if dry_run:
            return ()
        cache = self._target(plan.rootfs, plan.cache_path)
        manifest = self._target(plan.rootfs, plan.manifest_path)
        for path in (cache, manifest):
            if path.is_symlink():
                raise RustDeskPackageError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(cache.suffix + ".tmp")
        shutil.copyfile(plan.artifact, temporary)
        temporary.chmod(0o644)
        temporary.replace(cache)
        manifest.write_text(json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest.chmod(0o640)
        try:
            for command in plan.install_commands():
                runner(command, check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RustDeskPackageError(f"Ha fallat la instal·lació RustDesk: {exc}") from exc
        return cache, manifest

    def uninstall(self, plan: RustDeskPackagePlan, *, dry_run: bool = False, runner: Runner = subprocess.run) -> tuple[Path, ...]:
        if dry_run:
            return ()
        try:
            for command in plan.uninstall_commands():
                runner(command, check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RustDeskPackageError(f"Ha fallat la desinstal·lació RustDesk: {exc}") from exc
        removed: list[Path] = []
        for path in (self._target(plan.rootfs, plan.cache_path), self._target(plan.rootfs, plan.manifest_path)):
            if path.is_symlink():
                raise RustDeskPackageError(f"No s'eliminarà un enllaç simbòlic: {path}")
            if path.exists():
                path.unlink()
                removed.append(path)
        return tuple(removed)
