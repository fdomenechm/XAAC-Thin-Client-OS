from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from xaac_thin_client_os.agent_release_import import (
    AgentReleaseImportError,
    import_agent_release,
)
from xaac_thin_client_os.block7_release import (
    Block7ReleaseError,
    provenance_path_for_artifact,
    validate_block7_release_provenance,
    validate_canonical_release_artifact,
)

ROOT = Path(__file__).resolve().parents[1]


def _canonical_candidate(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = ROOT / "packages/xaac-agent_1.0.0-8_amd64.deb"
    candidate = tmp_path / source.name
    shutil.copy2(source, candidate)
    payload = json.loads(provenance_path_for_artifact(source).read_text(encoding="utf-8"))
    payload["canonical"] = True
    payload["build_method"] = "dpkg-buildpackage"
    payload["build_command"] = "dpkg-buildpackage -us -uc -b"
    provenance_path_for_artifact(candidate).write_text(json.dumps(payload), encoding="utf-8")
    return candidate


def _minimal_import_project(tmp_path: Path) -> Path:
    project = tmp_path / "os"
    (project / "config").mkdir(parents=True)
    (project / "packages").mkdir()
    (project / "assets/runtime").mkdir(parents=True)
    for name in ("xaac-agent-package.yaml", "local-integration.yaml", "kiosk-user.yaml", "xms-enrollment.yaml"):
        shutil.copy2(ROOT / "config" / name, project / "config" / name)
    shutil.copy2(ROOT / "assets/runtime/xaac-vpn-admin", project / "assets/runtime/xaac-vpn-admin")
    source = ROOT / "packages/xaac-agent_1.0.0-8_amd64.deb"
    shutil.copy2(source, project / "packages" / source.name)
    shutil.copy2(provenance_path_for_artifact(source), project / "packages" / provenance_path_for_artifact(source).name)
    return project


def test_embedded_test_artifact_is_explicitly_noncanonical() -> None:
    result = validate_block7_release_provenance(ROOT, require_canonical=False)
    assert result.canonical is False
    assert result.debian_version == "1.0.0-8"
    assert result.build_method == "dpkg-deb-fallback"
    with pytest.raises(Block7ReleaseError, match="agent_release_not_canonical"):
        validate_block7_release_provenance(ROOT, require_canonical=True)


def test_release_gate_is_machine_readable_and_rejects_fallback() -> None:
    script = ROOT / "scripts/validate-block7-release.sh"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert "BASH_SOURCE" not in text
    assert "pipefail" not in text
    completed = subprocess.run([str(script)], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload == {
        "schema": "xaac-block7-release-gate/v1",
        "passed": False,
        "error": "agent_release_not_canonical",
    }


def test_standalone_canonical_artifact_can_be_validated_before_import(tmp_path: Path) -> None:
    candidate = _canonical_candidate(tmp_path)
    result = validate_canonical_release_artifact(
        candidate,
        expected_application_version="1.0.0",
        expected_architecture="amd64",
    )
    assert result.canonical is True
    assert result.debian_version == "1.0.0-8"


def test_importer_rejects_noncanonical_artifact_without_modifying_project(tmp_path: Path) -> None:
    project = _minimal_import_project(tmp_path)
    profile_before = (project / "config/xaac-agent-package.yaml").read_bytes()
    candidate = tmp_path / "candidate" / "xaac-agent_1.0.0-8_amd64.deb"
    candidate.parent.mkdir()
    shutil.copy2(ROOT / "packages/xaac-agent_1.0.0-8_amd64.deb", candidate)
    shutil.copy2(
        ROOT / "packages/xaac-agent_1.0.0-8_amd64.deb.provenance.json",
        provenance_path_for_artifact(candidate),
    )
    with pytest.raises(AgentReleaseImportError, match="agent_release_not_canonical"):
        import_agent_release(project, candidate)
    assert (project / "config/xaac-agent-package.yaml").read_bytes() == profile_before


def test_importer_installs_canonical_deb_and_updates_profile_transactionally(tmp_path: Path) -> None:
    project = _minimal_import_project(tmp_path)
    candidate = _canonical_candidate(tmp_path / "candidate")
    result = import_agent_release(project, candidate)
    assert result.version == "1.0.0-8"
    assert result.artifact == "packages/xaac-agent_1.0.0-8_amd64.deb"
    validated = validate_block7_release_provenance(project, require_canonical=True)
    assert validated.canonical is True
    assert validated.sha256 == result.sha256


def test_import_script_is_posix_and_accepts_a_deb_not_agent_source() -> None:
    script = (ROOT / "scripts/import-xaac-agent-package.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/bin/sh\n")
    assert "BASH_SOURCE" not in script
    assert "pipefail" not in script
    assert "build-debian-release.sh" not in script
    assert "finalize-block7-release" not in script
    assert "provenance.json" in script
    assert "build-production-iso.sh --clean" in script


def test_os_tree_does_not_contain_agent_source_finalizer() -> None:
    assert not (ROOT / "scripts/finalize-block7-release.sh").exists()


def test_production_iso_wrapper_requires_canonical_release_before_system_tools() -> None:
    text = (ROOT / "scripts/build-production-iso.sh").read_text(encoding="utf-8")
    release_gate = text.index('"$PROJECT_ROOT/scripts/validate-block7-release.sh"')
    integration_gate = text.index('"$PROJECT_ROOT/scripts/validate-block7-integration.sh"')
    deps = text.index('for command in debootstrap')
    assert release_gate < integration_gate < deps


def test_os_build_dependencies_do_not_include_agent_build_toolchain() -> None:
    script = (ROOT / "scripts/install-build-dependencies.sh").read_text(encoding="utf-8")
    for package in ("debhelper", "python3-pytest", "python3-cryptography", "python3-cffi-backend"):
        assert package not in script
