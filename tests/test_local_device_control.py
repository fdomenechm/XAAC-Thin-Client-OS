from pathlib import Path

import pytest

from xaac_thin_client_os.local_device_control import (
    LocalDeviceControlConfigurator,
    LocalDeviceControlError,
    create_local_device_control_plan,
    load_local_device_control_profile,
)


def test_load_profile(project_root: Path) -> None:
    profile = load_local_device_control_profile(project_root / "config/local-device-control.yaml")
    assert profile["policy"]["default_decision"] == "deny"
    assert profile["storage"]["automount"] is False


def test_plan_blocks_storage_and_cameras(project_root: Path, tmp_path: Path) -> None:
    plan = create_local_device_control_plan(tmp_path / "rootfs", project_root / "config/local-device-control.yaml")
    contents = {str(path): content for path, content, _ in plan.files}
    assert 'ATTR{authorized}="0"' in contents["/etc/udev/rules.d/80-xaac-kiosk-local-devices.rules"]
    assert 'bDeviceClass}=="08"' not in contents["/etc/udev/rules.d/80-xaac-kiosk-local-devices.rules"]
    assert "polkit.Result.NO" in contents["/etc/polkit-1/rules.d/80-xaac-kiosk-udisks.rules"]


def test_execute_is_idempotent(project_root: Path, tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    plan = create_local_device_control_plan(rootfs, project_root / "config/local-device-control.yaml")
    configurator = LocalDeviceControlConfigurator()
    first = configurator.execute(plan)
    second = configurator.execute(plan)
    assert first == second
    assert len(first) == 3


def test_dry_run_writes_nothing(project_root: Path, tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    plan = create_local_device_control_plan(rootfs, project_root / "config/local-device-control.yaml")
    assert LocalDeviceControlConfigurator().execute(plan, dry_run=True) == ()
    assert not rootfs.exists()


def test_rejects_unsafe_rootfs(project_root: Path) -> None:
    with pytest.raises(LocalDeviceControlError):
        create_local_device_control_plan(Path("/tmp"), project_root / "config/local-device-control.yaml")


def test_rejects_symlink(project_root: Path, tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    target = rootfs / "etc/udev/rules.d/80-xaac-kiosk-local-devices.rules"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    plan = create_local_device_control_plan(rootfs, project_root / "config/local-device-control.yaml")
    with pytest.raises(LocalDeviceControlError):
        LocalDeviceControlConfigurator().execute(plan)
