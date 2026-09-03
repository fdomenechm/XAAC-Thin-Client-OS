"""Transactional import of a canonical XAAC Agent Debian release into XAAC Thin Client OS."""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from xaac_thin_client_os.block7_integration import (
    Block7IntegrationError,
    validate_packaged_block7_integration,
)
from xaac_thin_client_os.block7_release import (
    Block7ReleaseError,
    provenance_path_for_artifact,
    validate_block7_release_provenance,
    validate_canonical_release_artifact,
)
from xaac_thin_client_os.xaac_agent_package import (
    XaacAgentPackageError,
    load_xaac_agent_profile,
)


class AgentReleaseImportError(RuntimeError):
    """Raised when a canonical Agent release cannot be safely imported."""


@dataclass(frozen=True, slots=True)
class ImportedAgentRelease:
    version: str
    artifact: str
    sha256: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": "xaac-agent-release-import/v1",
            "imported": True,
            "version": self.version,
            "artifact": self.artifact,
            "sha256": self.sha256,
        }


def _write_profile(path: Path, profile: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump(profile, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def import_agent_release(project_root: Path, artifact: Path) -> ImportedAgentRelease:
    """Import one canonical Agent .deb and its adjacent provenance document transactionally."""
    root = project_root.resolve()
    source = artifact.expanduser().resolve()
    source_provenance = provenance_path_for_artifact(source)
    profile_path = root / "config/xaac-agent-package.yaml"
    package_dir = root / "packages"
    try:
        profile = load_xaac_agent_profile(profile_path)
        provenance = validate_canonical_release_artifact(
            source,
            provenance_path=source_provenance,
            expected_application_version=str(profile["package"]["application_version"]),
            expected_architecture=str(profile["package"]["architecture"]),
        )
    except (XaacAgentPackageError, Block7ReleaseError) as exc:
        raise AgentReleaseImportError(str(exc)) from exc

    package_dir.mkdir(parents=True, exist_ok=True)
    destination = package_dir / source.name
    destination_provenance = provenance_path_for_artifact(destination)

    with tempfile.TemporaryDirectory(prefix="xaac-agent-import-") as temporary:
        backup = Path(temporary)
        backup_profile = backup / profile_path.name
        shutil.copy2(profile_path, backup_profile)
        existing = sorted(package_dir.glob("xaac-agent_*.deb")) + sorted(
            package_dir.glob("xaac-agent_*.deb.provenance.json")
        )
        backup_packages = backup / "packages"
        backup_packages.mkdir()
        for path in existing:
            shutil.copy2(path, backup_packages / path.name)

        staged_artifact = backup / source.name
        staged_provenance = backup / source_provenance.name
        shutil.copy2(source, staged_artifact)
        shutil.copy2(source_provenance, staged_provenance)

        try:
            for path in existing:
                path.unlink()
            shutil.copy2(staged_artifact, destination)
            shutil.copy2(staged_provenance, destination_provenance)
            profile["package"]["version"] = provenance.debian_version
            profile["package"]["artifact"] = f"packages/{destination.name}"
            profile["package"]["sha256"] = provenance.sha256
            _write_profile(profile_path, profile)
            validate_block7_release_provenance(root, require_canonical=True)
            validate_packaged_block7_integration(root)
        except (OSError, Block7ReleaseError, Block7IntegrationError, XaacAgentPackageError) as exc:
            for path in package_dir.glob("xaac-agent_*.deb"):
                path.unlink(missing_ok=True)
            for path in package_dir.glob("xaac-agent_*.deb.provenance.json"):
                path.unlink(missing_ok=True)
            shutil.copy2(backup_profile, profile_path)
            for path in backup_packages.iterdir():
                shutil.copy2(path, package_dir / path.name)
            raise AgentReleaseImportError(f"agent_release_import_failed:{exc}") from exc

    return ImportedAgentRelease(
        version=provenance.debian_version,
        artifact=f"packages/{destination.name}",
        sha256=provenance.sha256,
    )


def payload_json(result: ImportedAgentRelease) -> str:
    return json.dumps(result.to_payload(), sort_keys=True)
