"""Transactional import of XAAC component Debian releases into XAAC Thin Client OS."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ComponentReleaseImportError(RuntimeError):
    """Raised when a component release cannot be safely imported."""


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    key: str
    package_name: str
    profile_name: str
    artifact_glob: str
    evidence_glob: str


@dataclass(frozen=True, slots=True)
class ImportedComponentRelease:
    component: str
    version: str
    architecture: str
    artifact: str
    evidence: str
    sha256: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": "xaac-component-release-import/v1",
            "imported": True,
            "component": self.component,
            "version": self.version,
            "architecture": self.architecture,
            "artifact": self.artifact,
            "evidence": self.evidence,
            "sha256": self.sha256,
        }


SPECS: dict[str, ComponentSpec] = {
    "network": ComponentSpec(
        key="network",
        package_name="xaac-thin-client-network",
        profile_name="xaac-thin-client-network-package.yaml",
        artifact_glob="xaac-thin-client-network_*.deb",
        evidence_glob="xaac-thin-client-network*.json",
    ),
    "vpn": ComponentSpec(
        key="vpn",
        package_name="xaac-thin-client-vpn",
        profile_name="xaac-thin-client-vpn-package.yaml",
        artifact_glob="xaac-thin-client-vpn_*.deb",
        evidence_glob="xaac-thin-client-vpn*.json",
    ),
    "remote": ComponentSpec(
        key="remote",
        package_name="xaac-thinclient",
        profile_name="xaac-thin-client-package.yaml",
        artifact_glob="xaac-thinclient_*.deb",
        evidence_glob="xaac-thinclient*.json",
    ),
    "dock": ComponentSpec(
        key="dock",
        package_name="xaac-thin-client-dock",
        profile_name="xaac-thin-client-dock-package.yaml",
        artifact_glob="xaac-thin-client-dock_*.deb",
        evidence_glob="xaac-thin-client-dock*.json",
    ),
}


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ComponentReleaseImportError(f"profile_invalid:{path}:{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("package"), dict):
        raise ComponentReleaseImportError(f"profile_invalid:{path}:missing_package")
    return data


def _write_profile(path: Path, profile: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump(profile, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_debian_package(path: Path) -> tuple[str, str, str]:
    try:
        if path.read_bytes()[:8] != b"!<arch>\n":
            raise ComponentReleaseImportError(f"artifact_not_deb:{path}")
        result = subprocess.run(
            (
                "dpkg-deb",
                "--show",
                "--showformat=${Package}\n${Version}\n${Architecture}\n",
                str(path),
            ),
            check=True,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ComponentReleaseImportError(f"artifact_inspection_failed:{path}:{exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise ComponentReleaseImportError(f"artifact_inspection_failed:{path}:{exc}") from exc
    lines = result.stdout.splitlines()
    if len(lines) < 3:
        raise ComponentReleaseImportError(f"artifact_metadata_incomplete:{path}")
    return lines[0], lines[1], lines[2]


def _json_candidates(artifact: Path) -> list[Path]:
    basename = artifact.name.removesuffix(".deb")
    candidates = [
        artifact.with_suffix(".json"),
        artifact.with_name(f"{basename}.evidence.json"),
        artifact.with_name(f"{basename}.provenance.json"),
    ]
    candidates.extend(sorted(artifact.parent.glob("*.json")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            unique.append(candidate)
            seen.add(resolved)
    return unique


def _evidence_artifact_name(payload: dict[str, Any]) -> str | None:
    artifact = payload.get("artifact")
    if isinstance(artifact, str):
        return Path(artifact).name
    if isinstance(artifact, dict):
        filename = artifact.get("filename")
        if isinstance(filename, str):
            return Path(filename).name
    filename = payload.get("filename")
    if isinstance(filename, str):
        return Path(filename).name
    artifact_path = payload.get("artifact_path")
    if isinstance(artifact_path, str):
        return Path(artifact_path).name
    return None


def _evidence_sha256(payload: dict[str, Any]) -> str | None:
    direct = payload.get("sha256")
    if isinstance(direct, str):
        return direct
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        nested = artifact.get("sha256")
        if isinstance(nested, str):
            return nested
    return None


def _evidence_size(payload: dict[str, Any]) -> int | None:
    for key in ("size_bytes", "size"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        for key in ("size_bytes", "size"):
            value = artifact.get(key)
            if isinstance(value, int):
                return value
    return None


def _load_matching_evidence(
    artifact: Path,
    *,
    package_name: str,
    version: str,
    architecture: str,
    sha256: str,
) -> tuple[Path, dict[str, Any]]:
    failures: list[str] = []
    for candidate in _json_candidates(artifact):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"{candidate.name}:invalid_json:{exc}")
            continue
        if not isinstance(payload, dict):
            failures.append(f"{candidate.name}:invalid_payload")
            continue
        if payload.get("package") != package_name:
            continue
        if str(payload.get("version", "")) != version:
            failures.append(f"{candidate.name}:version_mismatch")
            continue
        evidence_arch = payload.get("architecture")
        if evidence_arch is not None and str(evidence_arch) != architecture:
            failures.append(f"{candidate.name}:architecture_mismatch")
            continue
        artifact_name = _evidence_artifact_name(payload)
        if artifact_name is not None and artifact_name != artifact.name:
            failures.append(f"{candidate.name}:artifact_mismatch")
            continue
        evidence_sha = _evidence_sha256(payload)
        if evidence_sha != sha256:
            failures.append(f"{candidate.name}:sha256_mismatch")
            continue
        evidence_size = _evidence_size(payload)
        if evidence_size is not None and evidence_size != artifact.stat().st_size:
            failures.append(f"{candidate.name}:size_mismatch")
            continue
        return candidate, payload
    detail = ",".join(failures) if failures else "not_found"
    raise ComponentReleaseImportError(f"evidence_invalid:{artifact.name}:{detail}")


def _validate_profile_artifact(profile_path: Path, project_root: Path) -> None:
    profile = _load_yaml(profile_path)
    package = profile["package"]
    try:
        expected_name = str(package["name"])
        expected_version = str(package["version"])
        expected_architecture = str(package["architecture"])
        expected_sha256 = str(package["sha256"])
        artifact = (project_root / str(package["artifact"])).resolve()
        artifact.relative_to(project_root.resolve())
    except (KeyError, TypeError, ValueError) as exc:
        raise ComponentReleaseImportError(f"profile_invalid:{profile_path}:{exc}") from exc
    if not artifact.is_file() or artifact.is_symlink():
        raise ComponentReleaseImportError(f"profile_artifact_missing:{artifact}")
    actual_name, actual_version, actual_architecture = _inspect_debian_package(artifact)
    if (actual_name, actual_version, actual_architecture) != (
        expected_name,
        expected_version,
        expected_architecture,
    ):
        raise ComponentReleaseImportError(
            "profile_metadata_mismatch:"
            f"{actual_name}:{actual_version}:{actual_architecture}"
        )
    if _sha256(artifact) != expected_sha256:
        raise ComponentReleaseImportError(f"profile_sha256_mismatch:{artifact.name}")


def import_component_release(
    project_root: Path,
    artifact: Path,
    *,
    component: str,
) -> ImportedComponentRelease:
    """Import one component .deb and its build evidence transactionally."""
    try:
        spec = SPECS[component]
    except KeyError as exc:
        raise ComponentReleaseImportError(f"unknown_component:{component}") from exc

    root = project_root.resolve()
    source = artifact.expanduser().resolve()
    profile_path = root / "config" / spec.profile_name
    package_dir = root / "packages"
    if not source.is_file() or source.is_symlink():
        raise ComponentReleaseImportError(f"artifact_missing:{source}")

    profile = _load_yaml(profile_path)
    package = profile["package"]
    expected_name = str(package.get("name", ""))
    expected_version = str(package.get("version", ""))
    expected_architecture = str(package.get("architecture", ""))
    if expected_name != spec.package_name:
        raise ComponentReleaseImportError(
            f"profile_package_mismatch:{expected_name}:{spec.package_name}"
        )

    actual_name, actual_version, actual_architecture = _inspect_debian_package(source)
    if actual_name != spec.package_name:
        raise ComponentReleaseImportError(
            f"package_name_mismatch:{actual_name}:{spec.package_name}"
        )
    if actual_version != expected_version:
        raise ComponentReleaseImportError(
            f"package_version_mismatch:{actual_version}:{expected_version}"
        )
    if actual_architecture != expected_architecture:
        raise ComponentReleaseImportError(
            f"package_architecture_mismatch:{actual_architecture}:{expected_architecture}"
        )

    actual_sha256 = _sha256(source)
    evidence_path, _ = _load_matching_evidence(
        source,
        package_name=actual_name,
        version=actual_version,
        architecture=actual_architecture,
        sha256=actual_sha256,
    )

    package_dir.mkdir(parents=True, exist_ok=True)
    destination = package_dir / source.name
    destination_evidence = package_dir / evidence_path.name

    with tempfile.TemporaryDirectory(prefix=f"xaac-{component}-import-") as temporary:
        backup = Path(temporary)
        backup_profile = backup / profile_path.name
        shutil.copy2(profile_path, backup_profile)
        existing = sorted(package_dir.glob(spec.artifact_glob)) + sorted(
            package_dir.glob(spec.evidence_glob)
        )
        backup_packages = backup / "packages"
        backup_packages.mkdir()
        for path in existing:
            if path.is_file() and not path.is_symlink():
                shutil.copy2(path, backup_packages / path.name)

        staged_artifact = backup / source.name
        staged_evidence = backup / evidence_path.name
        shutil.copy2(source, staged_artifact)
        shutil.copy2(evidence_path, staged_evidence)

        try:
            for path in existing:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            shutil.copy2(staged_artifact, destination)
            shutil.copy2(staged_evidence, destination_evidence)
            package["artifact"] = f"packages/{destination.name}"
            package["sha256"] = actual_sha256
            _write_profile(profile_path, profile)
            _validate_profile_artifact(profile_path, root)
        except (OSError, ComponentReleaseImportError) as exc:
            for path in package_dir.glob(spec.artifact_glob):
                path.unlink(missing_ok=True)
            for path in package_dir.glob(spec.evidence_glob):
                path.unlink(missing_ok=True)
            shutil.copy2(backup_profile, profile_path)
            for path in backup_packages.iterdir():
                shutil.copy2(path, package_dir / path.name)
            raise ComponentReleaseImportError(
                f"component_release_import_failed:{component}:{exc}"
            ) from exc

    return ImportedComponentRelease(
        component=component,
        version=actual_version,
        architecture=actual_architecture,
        artifact=f"packages/{destination.name}",
        evidence=f"packages/{destination_evidence.name}",
        sha256=actual_sha256,
    )
