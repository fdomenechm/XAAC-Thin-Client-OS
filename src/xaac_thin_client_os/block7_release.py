"""Canonical release provenance gate for the final Block 7 ISO build."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xaac_thin_client_os.xaac_agent_package import (
    XaacAgentPackageError,
    inspect_agent_package,
    load_xaac_agent_profile,
)


class Block7ReleaseError(RuntimeError):
    """Raised when the embedded Agent was not built by the canonical release path."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = "xaac-block7-release-provenance/v1"
_CANONICAL_METHOD = "dpkg-buildpackage"
_CANONICAL_COMMAND = "dpkg-buildpackage -us -uc -b"


@dataclass(frozen=True, slots=True)
class Block7ReleaseProvenance:
    canonical: bool
    package: str
    application_version: str
    debian_version: str
    architecture: str
    artifact: str
    sha256: str
    build_method: str
    build_command: str
    source_date_epoch: int
    release_manifest_sha256: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "canonical": self.canonical,
            "package": self.package,
            "application_version": self.application_version,
            "debian_version": self.debian_version,
            "architecture": self.architecture,
            "artifact": self.artifact,
            "sha256": self.sha256,
            "build_method": self.build_method,
            "build_command": self.build_command,
            "source_date_epoch": self.source_date_epoch,
            "release_manifest_sha256": self.release_manifest_sha256,
        }


def provenance_path_for_artifact(artifact: Path) -> Path:
    return artifact.with_name(artifact.name + ".provenance.json")


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Block7ReleaseError("agent_release_provenance_unreadable") from exc
    expected = {
        "schema", "canonical", "package", "application_version", "debian_version",
        "architecture", "artifact", "sha256", "build_method", "build_command",
        "source_date_epoch", "release_manifest_sha256",
    }
    if not isinstance(raw, dict) or set(raw) != expected or raw.get("schema") != _SCHEMA:
        raise Block7ReleaseError("agent_release_provenance_schema_invalid")
    return raw


def validate_block7_release_provenance(
    project_root: Path,
    *,
    require_canonical: bool = True,
) -> Block7ReleaseProvenance:
    root = project_root.resolve()
    try:
        profile = load_xaac_agent_profile(root / "config/xaac-agent-package.yaml")
    except XaacAgentPackageError as exc:
        raise Block7ReleaseError(f"agent_profile_invalid:{exc}") from exc

    artifact = (root / str(profile["package"]["artifact"])).resolve()
    try:
        artifact.relative_to(root)
        metadata = inspect_agent_package(artifact)
    except (ValueError, XaacAgentPackageError) as exc:
        raise Block7ReleaseError("agent_release_artifact_invalid") from exc

    payload = _load_payload(provenance_path_for_artifact(artifact))
    try:
        epoch = int(payload["source_date_epoch"])
    except (TypeError, ValueError) as exc:
        raise Block7ReleaseError("agent_release_source_date_epoch_invalid") from exc

    provenance = Block7ReleaseProvenance(
        canonical=payload["canonical"] is True,
        package=str(payload["package"]),
        application_version=str(payload["application_version"]),
        debian_version=str(payload["debian_version"]),
        architecture=str(payload["architecture"]),
        artifact=str(payload["artifact"]),
        sha256=str(payload["sha256"]),
        build_method=str(payload["build_method"]),
        build_command=str(payload["build_command"]),
        source_date_epoch=epoch,
        release_manifest_sha256=str(payload["release_manifest_sha256"]),
    )

    package = profile["package"]
    expected_identity = (
        package["name"], package["application_version"], package["version"],
        package["architecture"], artifact.name, package["sha256"],
    )
    actual_identity = (
        provenance.package, provenance.application_version, provenance.debian_version,
        provenance.architecture, provenance.artifact, provenance.sha256,
    )
    if actual_identity != expected_identity:
        raise Block7ReleaseError("agent_release_provenance_identity_mismatch")
    if (metadata.package, metadata.version, metadata.architecture, metadata.sha256) != (
        provenance.package, provenance.debian_version, provenance.architecture, provenance.sha256,
    ):
        raise Block7ReleaseError("agent_release_provenance_artifact_mismatch")
    if provenance.source_date_epoch <= 0:
        raise Block7ReleaseError("agent_release_source_date_epoch_invalid")
    if not _SHA256.fullmatch(provenance.release_manifest_sha256):
        raise Block7ReleaseError("agent_release_manifest_sha256_invalid")
    if require_canonical and (
        not provenance.canonical
        or provenance.build_method != _CANONICAL_METHOD
        or provenance.build_command != _CANONICAL_COMMAND
    ):
        raise Block7ReleaseError("agent_release_not_canonical")
    return provenance
