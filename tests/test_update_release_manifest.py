from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaac_thin_client_os.cli import main
from xaac_thin_client_os.update_release_manifest import (
    UpdateReleaseManifestError,
    build_release_manifest,
    load_release_manifest,
    write_release_manifest,
)

ROOT = Path(__file__).parents[1]


def test_builds_manifest_from_exact_production_debs() -> None:
    manifest = build_release_manifest(
        ROOT,
        ROOT / "config/update-model.yaml",
        target_os_version="1.1.0",
        channel="production",
    )
    assert manifest["schema"] == "xaac-update-manifest/v1"
    assert manifest["release"]["hardware_profile"] == "wyse3040"
    assert [item["package"] for item in manifest["components"]] == [
        "xaac-thinclient",
        "xaac-thin-client-vpn",
        "xaac-thin-client-network",
        "xaac-thin-client-dock",
        "xaac-agent",
    ]
    assert all(len(item["sha256"]) == 64 for item in manifest["components"])
    assert manifest["verification"]["detached_signature_required"] is True


def test_manifest_is_deterministic() -> None:
    first = build_release_manifest(ROOT, ROOT / "config/update-model.yaml", target_os_version="1.1.0", channel="production")
    second = build_release_manifest(ROOT, ROOT / "config/update-model.yaml", target_os_version="1.1.0", channel="production")
    assert first == second


def test_written_manifest_detects_tampering(tmp_path: Path) -> None:
    manifest = build_release_manifest(ROOT, ROOT / "config/update-model.yaml", target_os_version="1.1.0", channel="production")
    path = write_release_manifest(tmp_path / "manifest.json", manifest)
    assert load_release_manifest(path)["release"]["os_version"] == "1.1.0"
    payload = json.loads(path.read_text())
    payload["release"]["os_version"] = "9.9.9"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(UpdateReleaseManifestError, match="modificat"):
        load_release_manifest(path)


def test_rejects_invalid_target_version() -> None:
    with pytest.raises(UpdateReleaseManifestError, match="Versió objectiu"):
        build_release_manifest(ROOT, ROOT / "config/update-model.yaml", target_os_version="latest", channel="production")


def test_rejects_unknown_channel() -> None:
    with pytest.raises(UpdateReleaseManifestError, match="Canal no autoritzat"):
        build_release_manifest(ROOT, ROOT / "config/update-model.yaml", target_os_version="1.1.0", channel="unknown")


def test_cli_creates_update_manifest(tmp_path: Path) -> None:
    # Use the real project because the manifest deliberately validates the exact .deb artifacts.
    output = ".build/test-phase-10-1-manifest.json"
    destination = ROOT / output
    try:
        assert main(["--root", str(ROOT), "create-update-manifest", "--output", output]) == 0
        assert load_release_manifest(destination)["release"]["os_version"] == "1.1.0"
    finally:
        destination.unlink(missing_ok=True)
