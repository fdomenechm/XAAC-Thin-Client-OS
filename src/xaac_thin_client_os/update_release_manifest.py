"""Release manifest generation for XAAC Thin Client OS updates (phase 10.1)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from xaac_thin_client_os.update_model import UpdateModelError, load_update_model


class UpdateReleaseManifestError(RuntimeError):
    """Raised when an update release manifest cannot be built safely."""


_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def manifest_payload_hash(payload: dict[str, Any]) -> str:
    clean = {key: value for key, value in payload.items() if key != "integrity"}
    return hashlib.sha256(canonical_json(clean)).hexdigest()


def _load_package_config(project_root: Path, relative: str) -> dict[str, Any]:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise UpdateReleaseManifestError(f"Ruta de configuració de paquet insegura: {relative}")
    source = project_root / Path(*path.parts)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UpdateReleaseManifestError(f"No s'ha pogut carregar {relative}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("package"), dict):
        raise UpdateReleaseManifestError(f"Configuració de paquet invàlida: {relative}")
    return raw


def _artifact_path(project_root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise UpdateReleaseManifestError("Ruta d'artefacte absent")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise UpdateReleaseManifestError(f"Ruta d'artefacte insegura: {value}")
    path = (project_root / Path(*relative.parts)).resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError as exc:
        raise UpdateReleaseManifestError(f"L'artefacte ix del projecte: {value}") from exc
    if not path.is_file() or path.is_symlink():
        raise UpdateReleaseManifestError(f"Artefacte absent o insegur: {value}")
    return path


def _deb_metadata(path: Path) -> tuple[str, str, str]:
    try:
        result = subprocess.run(
            ["dpkg-deb", "-W", "--showformat=${Package}\n${Version}\n${Architecture}\n", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateReleaseManifestError(f"No s'ha pogut inspeccionar {path.name}: {exc}") from exc
    values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(values) != 3:
        raise UpdateReleaseManifestError(f"Metadades Debian incompletes en {path.name}")
    return values[0], values[1], values[2]


def build_release_manifest(
    project_root: Path,
    policy_path: Path,
    *,
    target_os_version: str,
    channel: str,
    minimum_installed_os_version: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic manifest from the exact .deb artifacts in the source tree."""
    root = project_root.resolve()
    try:
        policy = load_update_model(policy_path)
    except UpdateModelError as exc:
        raise UpdateReleaseManifestError(str(exc)) from exc
    if not _SEMVER.fullmatch(target_os_version):
        raise UpdateReleaseManifestError("Versió objectiu del sistema invàlida")
    channel_ids = [item["id"] for item in policy["channels"]]
    if channel not in channel_ids:
        raise UpdateReleaseManifestError(f"Canal no autoritzat: {channel}")
    minimum = minimum_installed_os_version or policy["version_policy"]["minimum_os_version"]
    if not isinstance(minimum, str) or not _SEMVER.fullmatch(minimum):
        raise UpdateReleaseManifestError("Versió mínima instal·lada invàlida")

    components: list[dict[str, object]] = []
    for component in policy["components"]:
        package_config = _load_package_config(root, component["package_config"])
        package = package_config["package"]
        artifact = _artifact_path(root, package.get("artifact"))
        deb_name, deb_version, deb_architecture = _deb_metadata(artifact)
        if deb_name != component["package"]:
            raise UpdateReleaseManifestError(
                f"El paquet {artifact.name} declara {deb_name}, no {component['package']}"
            )
        expected_architecture = component["architecture"]
        if deb_architecture != expected_architecture:
            raise UpdateReleaseManifestError(
                f"Arquitectura inesperada en {artifact.name}: {deb_architecture}"
            )
        configured_version = package.get("version")
        if configured_version is not None and str(configured_version) != deb_version:
            raise UpdateReleaseManifestError(
                f"Versió incoherent per a {deb_name}: config={configured_version}, deb={deb_version}"
            )
        components.append(
            {
                "id": component["id"],
                "package": deb_name,
                "version": deb_version,
                "architecture": deb_architecture,
                "filename": artifact.name,
                "size_bytes": artifact.stat().st_size,
                "sha256": sha256_file(artifact),
            }
        )

    manifest: dict[str, Any] = {
        "schema": policy["manifest"]["schema"],
        "release": {
            "id": f"xaac-{target_os_version}-{channel}",
            "os_version": target_os_version,
            "channel": channel,
            "hardware_profile": policy["hardware_profile"],
            "architecture": policy["architecture"],
        },
        "compatibility": {
            "minimum_installed_os_version": minimum,
            "allow_downgrade": False,
            "require_complete_component_set": True,
            "atomic_component_set": list(policy["compatibility"]["atomic_component_set"]),
        },
        "components": components,
        "verification": {
            "hash_algorithm": "sha256",
            "detached_signature_required": True,
            "signature_suffix": policy["manifest"]["signature_suffix"],
            "keyring": policy["manifest"]["keyring"],
            "fail_closed": True,
        },
    }
    manifest["integrity"] = {
        "algorithm": "sha256",
        "manifest_payload": manifest_payload_hash(manifest),
    }
    return manifest


def write_release_manifest(path: Path, payload: dict[str, Any]) -> Path:
    """Atomically write one deterministic release manifest."""
    if path.is_symlink():
        raise UpdateReleaseManifestError(f"Destinació amb enllaç simbòlic: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
            stream.write(b"\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def load_release_manifest(path: Path) -> dict[str, Any]:
    """Load and verify the self-integrity field of a release manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateReleaseManifestError(f"Manifest il·legible: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "xaac-update-manifest/v1":
        raise UpdateReleaseManifestError("Esquema de manifest d'actualització invàlid")
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        raise UpdateReleaseManifestError("Integritat del manifest absent")
    expected = integrity.get("manifest_payload")
    if not isinstance(expected, str) or len(expected) != 64:
        raise UpdateReleaseManifestError("Hash intern del manifest invàlid")
    if manifest_payload_hash(payload) != expected:
        raise UpdateReleaseManifestError("El manifest ha estat modificat")
    return payload
