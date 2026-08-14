from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.local_integration import (
    LocalIntegrationConfigurator,
    LocalIntegrationError,
    load_local_integration_profile,
)


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "local-integration.yaml"
    path.write_text(Path("config/local-integration.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_profile_defines_directional_contract() -> None:
    profile = load_local_integration_profile(Path("config/local-integration.yaml"))
    assert profile["schema_version"] == 2
    assert profile["contract"]["formats"]["state"] == "xaac-state/v2"
    assert profile["principals"] == {
        "agent_user": "xaac-agent",
        "thin_client_user": "xaac-kiosk",
        "shared_group": "xaac-ipc",
    }
    assert profile["directories"]["state"]["owner"] == "xaac-kiosk"
    assert profile["directories"]["configuration"]["owner"] == "xaac-agent"
    assert profile["directories"]["events"]["path"] == "/run/xaac/thin-client/events"


def test_profile_rejects_socket_or_wrong_principals(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/local-integration.yaml").read_text())
    data["principals"]["thin_client_user"] = "xaac"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(LocalIntegrationError, match="Principals"):
        load_local_integration_profile(path)


def test_profile_rejects_world_accessible_directory(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/local-integration.yaml").read_text())
    data["directories"]["events"]["mode"] = "2777"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(LocalIntegrationError, match="massa permissiu"):
        load_local_integration_profile(path)


def test_installer_writes_configuration_tmpfiles_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    root.mkdir()
    plan = LocalIntegrationConfigurator().install(root, _profile(tmp_path))
    assert all(path.is_file() for path in plan.files)
    tmpfiles = plan.tmpfiles.read_text()
    assert "d /var/lib/xaac/thin-client/state 2750 xaac-kiosk xaac-ipc -" in tmpfiles
    assert "d /var/lib/xaac/thin-client/config 2750 xaac-agent xaac-ipc -" in tmpfiles
    assert "d /run/xaac/thin-client/events 2750 xaac-kiosk xaac-ipc -" in tmpfiles
    manifest = json.loads(plan.manifest.read_text())
    assert manifest["contract"] == "xaac-local-integration/v1"
    assert manifest["thin_client"] == {"package": "xaac-thinclient", "version": "1.0.0"}
    assert manifest["separation"]["events"] == "xaac-kiosk-writes-xaac-agent-reads"


def test_installer_dry_run_does_not_write(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    root.mkdir()
    plan = LocalIntegrationConfigurator().install(root, _profile(tmp_path), dry_run=True)
    assert len(plan.files) == 3
    assert not plan.configuration.exists()


def test_installer_rejects_symlink_destination(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    (root / "etc/xaac").mkdir(parents=True)
    (root / "etc/xaac/local-integration.yaml").symlink_to("/tmp/unsafe")
    with pytest.raises(LocalIntegrationError, match="enllaç simbòlic"):
        LocalIntegrationConfigurator().install(root, _profile(tmp_path))


def test_cli_exposes_local_integration_command() -> None:
    args = build_parser().parse_args(["configure-local-integration", "--dry-run"])
    assert args.command == "configure-local-integration"
    assert args.dry_run is True
