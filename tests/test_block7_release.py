from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from xaac_thin_client_os.block7_release import (
    Block7ReleaseError,
    provenance_path_for_artifact,
    validate_block7_release_provenance,
)

ROOT = Path(__file__).resolve().parents[1]


def test_embedded_test_artifact_is_explicitly_noncanonical() -> None:
    result = validate_block7_release_provenance(ROOT, require_canonical=False)
    assert result.canonical is False
    assert result.debian_version == "1.0.0-7"
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


def test_canonical_provenance_accepts_matching_artifact(tmp_path: Path) -> None:
    project = tmp_path / "os"
    (project / "config").mkdir(parents=True)
    (project / "packages").mkdir()
    shutil.copy2(ROOT / "config/xaac-agent-package.yaml", project / "config/xaac-agent-package.yaml")
    artifact = ROOT / "packages/xaac-agent_1.0.0-7_amd64.deb"
    copied = project / "packages" / artifact.name
    shutil.copy2(artifact, copied)
    source = json.loads(provenance_path_for_artifact(artifact).read_text(encoding="utf-8"))
    source["canonical"] = True
    source["build_method"] = "dpkg-buildpackage"
    source["build_command"] = "dpkg-buildpackage -us -uc -b"
    provenance_path_for_artifact(copied).write_text(json.dumps(source), encoding="utf-8")
    result = validate_block7_release_provenance(project, require_canonical=True)
    assert result.canonical is True
    assert result.sha256 == source["sha256"]


def test_finalizer_is_posix_and_has_no_noncanonical_fallback() -> None:
    script = (ROOT / "scripts/finalize-block7-release.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/bin/sh\n")
    assert "BASH_SOURCE" not in script
    assert "pipefail" not in script
    assert "build-debian-release.sh" in script
    assert "validate-block7-release.sh" in script
    assert "validate-block7-integration.sh" in script
    assert "build-production-iso.sh\" --clean" in script
    assert "dpkg-deb --build" not in script


def test_production_iso_wrapper_requires_canonical_release_before_system_tools() -> None:
    text = (ROOT / "scripts/build-production-iso.sh").read_text(encoding="utf-8")
    gate = text.index('"$PROJECT_ROOT/scripts/validate-block7-release.sh"')
    deps = text.index('for command in debootstrap')
    assert gate < deps


def test_os_build_host_dependencies_cover_canonical_agent_build() -> None:
    script = (ROOT / "scripts/install-build-dependencies.sh").read_text(encoding="utf-8")
    for package in ("debhelper", "python3.13", "python3-pytest", "python3-cryptography", "python3-cffi-backend"):
        assert package in script
