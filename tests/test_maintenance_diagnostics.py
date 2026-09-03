from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.maintenance_diagnostics import (
    MaintenanceDiagnosticsError,
    MaintenanceDiagnosticsInstaller,
    create_maintenance_diagnostics_plan,
    load_maintenance_diagnostics,
)

ROOT = Path(__file__).parents[1]
PROFILE = ROOT / "config/maintenance-diagnostics.yaml"


def _profile(tmp_path: Path, mutate=None) -> Path:
    data = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    if mutate is not None:
        mutate(data)
    path = tmp_path / "maintenance.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_phase_10_3_profile_defines_single_admin_cli() -> None:
    profile = load_maintenance_diagnostics(PROFILE)
    assert profile["phase"] == "10.3"
    assert profile["commands"] == [
        "status",
        "health",
        "network",
        "storage",
        "services",
        "logs",
        "cleanup",
        "diagnostics",
    ]
    assert profile["outputs"]["admin"] == "/usr/local/sbin/xaac-maintenance"
    assert "ssh.service" in profile["services"]["active_required"]
    assert "systemd-timesyncd.service" in profile["services"]["active_required"]


def test_phase_10_3_privacy_is_fail_closed() -> None:
    profile = load_maintenance_diagnostics(PROFILE)
    privacy = profile["privacy"]
    assert privacy["sanitize_logs"] is True
    assert privacy["include_configuration_contents"] is False
    assert privacy["include_private_keys"] is False
    assert privacy["include_credentials"] is False
    assert privacy["include_vpn_secrets"] is False
    assert "/etc/NetworkManager/system-connections" in privacy["forbidden_paths"]
    assert "/etc/xaac-agent/enrollment.token" in privacy["forbidden_paths"]


def test_phase_10_3_rejects_relaxed_privacy(tmp_path: Path) -> None:
    profile = _profile(
        tmp_path,
        lambda data: data["privacy"].__setitem__("include_vpn_secrets", True),
    )
    with pytest.raises(MaintenanceDiagnosticsError, match="privacitat"):
        load_maintenance_diagnostics(profile)


def test_phase_10_3_rejects_unsafe_output_path(tmp_path: Path) -> None:
    profile = _profile(
        tmp_path,
        lambda data: data["outputs"].__setitem__("state", "/var/lib/../etc/passwd"),
    )
    with pytest.raises(MaintenanceDiagnosticsError, match="Ruta insegura"):
        load_maintenance_diagnostics(profile)


def test_phase_10_3_installer_writes_root_only_state_and_diagnostics(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    plan = create_maintenance_diagnostics_plan(rootfs, PROFILE)
    outputs = MaintenanceDiagnosticsInstaller().install(plan)
    assert len(outputs) == 3
    policy = json.loads(plan.output("policy").read_text(encoding="utf-8"))
    state = json.loads(plan.output("state").read_text(encoding="utf-8"))
    assert policy["maintenance_id"] == "xaac-maintenance"
    assert state["last_diagnostics_bundle"] is None
    assert stat.S_IMODE(plan.output("policy").stat().st_mode) == 0o640
    assert stat.S_IMODE(plan.output("state").stat().st_mode) == 0o640
    tmpfiles = plan.output("tmpfiles").read_text(encoding="utf-8")
    assert "d /var/lib/xaac-maintenance/diagnostics 0700 root root" in tmpfiles


def test_phase_10_3_installer_protects_symlink(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    plan = create_maintenance_diagnostics_plan(rootfs, PROFILE)
    target = plan.output("policy")
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("safe", encoding="utf-8")
    target.symlink_to(outside)
    with pytest.raises(MaintenanceDiagnosticsError, match="enllaç simbòlic"):
        MaintenanceDiagnosticsInstaller().install(plan)
    assert outside.read_text(encoding="utf-8") == "safe"


def test_phase_10_3_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_maintenance_diagnostics_plan(tmp_path / "rootfs", PROFILE)
    paths = MaintenanceDiagnosticsInstaller().install(plan, dry_run=True)
    assert not any(path.exists() for path in paths)
