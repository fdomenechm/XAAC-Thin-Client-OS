from pathlib import Path

import pytest

from xaac_thin_client_os.power_action_control import (
    PowerActionControlConfigurator,
    PowerActionControlError,
    create_power_action_control_plan,
    load_power_action_control_profile,
)


def test_load_profile(project_root: Path) -> None:
    profile = load_power_action_control_profile(project_root / "config/power-action-control.yaml")
    assert profile["policy"]["default_decision"] == "deny"
    assert profile["actions"]["poweroff"]["kiosk_user"] == "request-agent"
    assert profile["actions"]["suspend"]["kiosk_user"] == "deny"


def test_plan_blocks_direct_logind_actions(project_root: Path, tmp_path: Path) -> None:
    plan = create_power_action_control_plan(tmp_path / "rootfs", project_root / "config/power-action-control.yaml")
    contents = {str(path): content for path, content, _ in plan.files}
    assert "HandlePowerKey=ignore" in contents["/etc/systemd/logind.conf.d/40-xaac-power-control.conf"]
    assert "polkit.Result.NO" in contents["/etc/polkit-1/rules.d/90-xaac-kiosk-power.rules"]
    assert "UNIX-CONNECT:/run/xaac-agent/power-control.sock" in contents["/usr/local/libexec/xaac/request-power-action"]


def test_execute_is_idempotent(project_root: Path, tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    plan = create_power_action_control_plan(rootfs, project_root / "config/power-action-control.yaml")
    configurator = PowerActionControlConfigurator()
    assert configurator.execute(plan) == configurator.execute(plan)
    assert len(configurator.execute(plan)) == 4


def test_dry_run_writes_nothing(project_root: Path, tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    plan = create_power_action_control_plan(rootfs, project_root / "config/power-action-control.yaml")
    assert PowerActionControlConfigurator().execute(plan, dry_run=True) == ()
    assert not rootfs.exists()


def test_rejects_unsafe_rootfs(project_root: Path) -> None:
    with pytest.raises(PowerActionControlError):
        create_power_action_control_plan(Path("/tmp"), project_root / "config/power-action-control.yaml")


def test_rejects_symlink(project_root: Path, tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    target = rootfs / "etc/xaac/kiosk/power-action-control.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    plan = create_power_action_control_plan(rootfs, project_root / "config/power-action-control.yaml")
    with pytest.raises(PowerActionControlError):
        PowerActionControlConfigurator().execute(plan)
