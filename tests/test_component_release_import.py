from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.component_release_import import (
    ComponentReleaseImportError,
    SPECS,
    import_component_release,
)


ROOT = Path(__file__).resolve().parents[1]


CASES = {
    "network": "xaac-thin-client-network_1.1.0-1_all.deb",
    "vpn": "xaac-thin-client-vpn_1.1.0_all.deb",
    "remote": "xaac-thinclient_1.1.0_all.deb",
    "dock": "xaac-thin-client-dock_1.1.0_all.deb",
}


def _prepare_project(tmp_path: Path, component: str) -> tuple[Path, Path, Path]:
    spec = SPECS[component]
    project = tmp_path / "project"
    source_dir = tmp_path / "source"
    (project / "config").mkdir(parents=True)
    (project / "packages").mkdir()
    source_dir.mkdir()
    shutil.copy2(ROOT / "config" / spec.profile_name, project / "config" / spec.profile_name)
    artifact = source_dir / CASES[component]
    shutil.copy2(ROOT / "packages" / CASES[component], artifact)
    return project, source_dir, artifact


def _metadata(component: str) -> tuple[str, str, str]:
    profile = yaml.safe_load((ROOT / "config" / SPECS[component].profile_name).read_text())
    package = profile["package"]
    return str(package["name"]), str(package["version"]), str(package["architecture"])


def _write_evidence(component: str, source_dir: Path, artifact: Path) -> Path:
    package, version, architecture = _metadata(component)
    sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    size = artifact.stat().st_size
    if component == "network":
        evidence = source_dir / artifact.name.replace(".deb", ".json")
        payload = {
            "package": package,
            "version": version,
            "architecture": architecture,
            "filename": artifact.name,
            "sha256": sha256,
            "size": size,
        }
    elif component == "vpn":
        evidence = source_dir / artifact.name.replace(".deb", ".json")
        payload = {
            "format": "xaac-debian-build-evidence/v1",
            "package": package,
            "version": version,
            "architecture": architecture,
            "artifact": {
                "filename": artifact.name,
                "sha256": sha256,
                "size": size,
            },
        }
    elif component == "remote":
        evidence = source_dir / artifact.name.replace(".deb", ".evidence.json")
        payload = {
            "schema": "xaac-build-evidence/v1",
            "package": package,
            "version": version,
            "architecture": architecture,
            "artifact": artifact.name,
            "artifact_path": f"dist/{artifact.name}",
            "sha256": sha256,
            "size_bytes": size,
        }
    else:
        evidence = source_dir / "xaac-thin-client-dock-1.1.0.evidence.json"
        payload = {
            "package": package,
            "version": version,
            "artifact": artifact.name,
            "sha256": sha256,
            "size_bytes": size,
        }
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    return evidence


@pytest.mark.parametrize("component", tuple(CASES))
def test_import_component_release_accepts_each_evidence_format(
    tmp_path: Path,
    component: str,
) -> None:
    project, source_dir, artifact = _prepare_project(tmp_path, component)
    evidence = _write_evidence(component, source_dir, artifact)

    result = import_component_release(project, artifact, component=component)

    profile = yaml.safe_load((project / "config" / SPECS[component].profile_name).read_text())
    destination = project / result.artifact
    assert destination.read_bytes() == artifact.read_bytes()
    assert (project / result.evidence).read_bytes() == evidence.read_bytes()
    assert profile["package"]["artifact"] == result.artifact
    assert profile["package"]["sha256"] == result.sha256
    assert result.sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()


def test_import_component_release_rejects_stale_evidence(tmp_path: Path) -> None:
    project, source_dir, artifact = _prepare_project(tmp_path, "network")
    evidence = _write_evidence("network", source_dir, artifact)
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["sha256"] = "0" * 64
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    original_profile = (project / "config" / SPECS["network"].profile_name).read_bytes()

    with pytest.raises(ComponentReleaseImportError, match="evidence_invalid"):
        import_component_release(project, artifact, component="network")

    assert (project / "config" / SPECS["network"].profile_name).read_bytes() == original_profile
    assert not any((project / "packages").iterdir())


def test_component_import_scripts_are_present_and_posix() -> None:
    for component in CASES:
        script = ROOT / "scripts" / f"import-xaac-{component}-package.sh"
        source = script.read_text(encoding="utf-8")
        assert source.startswith("#!/bin/sh\n")
        assert "BASH_SOURCE" not in source
        assert "pipefail" not in source
        assert "component_release_import" in source
        assert script.stat().st_mode & 0o111


ACTUAL_EVIDENCE = {
    "network": "xaac-thin-client-network_1.1.0-1_all.json",
    "vpn": "xaac-thin-client-vpn_1.1.0_all.json",
    "remote": "xaac-thinclient_1.1.0_all.evidence.json",
    "dock": "xaac-thin-client-dock-1.1.0.evidence.json",
}


@pytest.mark.parametrize("component", tuple(CASES))
def test_embedded_component_evidence_is_importable(tmp_path: Path, component: str) -> None:
    project, source_dir, artifact = _prepare_project(tmp_path, component)
    shutil.copy2(ROOT / "packages" / ACTUAL_EVIDENCE[component], source_dir / ACTUAL_EVIDENCE[component])

    result = import_component_release(project, artifact, component=component)

    assert result.sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert (project / result.evidence).name == ACTUAL_EVIDENCE[component]
