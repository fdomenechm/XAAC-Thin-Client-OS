from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaac_thin_client_os.usb_peripherals import (
    UsbConfigurator,
    UsbDetector,
    UsbDevice,
    UsbInventory,
    UsbPeripheralError,
    compare_usb,
    create_usb_configuration_plan,
    load_usb_profile,
    write_usb_report,
)


def write(root: Path, rel: str, value: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def make_device(root: Path, name: str, *, vendor: str = "046d", product: str = "c52b", class_code: str = "03", version: str = "2.00", speed: str = "480", authorized: str = "1") -> None:
    base = root / "sys/bus/usb/devices" / name
    write(root, f"sys/bus/usb/devices/{name}/idVendor", vendor)
    write(root, f"sys/bus/usb/devices/{name}/idProduct", product)
    write(root, f"sys/bus/usb/devices/{name}/manufacturer", "Test")
    write(root, f"sys/bus/usb/devices/{name}/product", "Peripheral")
    write(root, f"sys/bus/usb/devices/{name}/version", version)
    write(root, f"sys/bus/usb/devices/{name}/speed", speed)
    write(root, f"sys/bus/usb/devices/{name}/authorized", authorized)
    write(root, f"sys/bus/usb/devices/{name}/bDeviceClass", "00")
    write(root, f"sys/bus/usb/devices/{name}:1.0/bInterfaceClass", class_code)
    assert base.exists()


def inventory(**changes: object) -> UsbInventory:
    values = {
        "usb2_controllers": 1,
        "usb3_controllers": 1,
        "devices": (UsbDevice("1-1", "046d", "c52b", "Logitech", "Keyboard", "2.00", 480, ("hid",), True),),
    }
    values.update(changes)
    return UsbInventory(**values)  # type: ignore[arg-type]


def test_detector_reads_controllers_and_hid(tmp_path: Path) -> None:
    write(tmp_path, "sys/bus/usb/devices/usb1/version", "2.00")
    write(tmp_path, "sys/bus/usb/devices/usb2/version", "3.00")
    make_device(tmp_path, "1-1")
    result = UsbDetector(root=tmp_path).detect()
    assert result.usb2_controllers == 1
    assert result.usb3_controllers == 1
    assert result.devices[0].classes == ("hid",)
    assert result.devices[0].vid_pid == "046d:c52b"


def test_detector_classifies_supported_classes(tmp_path: Path) -> None:
    for index, code in enumerate(("08", "0b", "07", "0e"), start=1):
        make_device(tmp_path, f"1-{index}", class_code=code, product=f"000{index}")
    classes = {item.classes[0] for item in UsbDetector(root=tmp_path).detect().devices}
    assert classes == {"storage", "smartcard", "printer", "camera"}


def test_detector_missing_sysfs_is_safe(tmp_path: Path) -> None:
    assert UsbDetector(root=tmp_path).detect() == UsbInventory(0, 0, ())


def test_detector_handles_invalid_speed(tmp_path: Path) -> None:
    make_device(tmp_path, "1-1", speed="unknown")
    assert UsbDetector(root=tmp_path).detect().devices[0].speed_mbps is None


def test_profile_loads(project_root: Path) -> None:
    assert load_usb_profile(project_root / "config/usb.yaml")["profile"] == "wyse3040"


@pytest.mark.parametrize("content", ["[]\n", "schema_version: 2\n", "schema_version: 1\nprofile: x\n", "schema_version: 1\nprofile: x\ncontrollers: {}\nclasses: {}\npolicy: {default_action: maybe}\nconfiguration: {}\npackages: []\n"])
def test_invalid_profile_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "usb.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(UsbPeripheralError):
        load_usb_profile(path)


def test_invalid_vid_pid_rejected(tmp_path: Path) -> None:
    path = tmp_path / "usb.yaml"
    path.write_text("schema_version: 1\nprofile: x\ncontrollers: {}\nclasses: {}\npolicy: {default_action: allow, blocked_vid_pid: [bad]}\nconfiguration: {}\npackages: []\n", encoding="utf-8")
    with pytest.raises(UsbPeripheralError, match="blocked_vid_pid"):
        load_usb_profile(path)


def test_compatible_usb_passes(project_root: Path) -> None:
    assert compare_usb(inventory(), load_usb_profile(project_root / "config/usb.yaml")).compatible


def test_missing_usb3_fails(project_root: Path) -> None:
    assert not compare_usb(inventory(usb3_controllers=0), load_usb_profile(project_root / "config/usb.yaml")).compatible


def test_missing_hid_fails(project_root: Path) -> None:
    assert not compare_usb(inventory(devices=()), load_usb_profile(project_root / "config/usb.yaml")).compatible


def test_optional_classes_warn(project_root: Path) -> None:
    report = compare_usb(inventory(), load_usb_profile(project_root / "config/usb.yaml"))
    assert report.compatible
    assert any(check.status == "warning" and check.name == "class-camera" for check in report.checks)


def test_unauthorized_device_warns(project_root: Path) -> None:
    device = UsbDevice("1-1", "046d", "c52b", "", "", "2.0", 480, ("hid",), False)
    report = compare_usb(inventory(devices=(device,)), load_usb_profile(project_root / "config/usb.yaml"))
    assert report.compatible
    assert next(check for check in report.checks if check.name == "device-authorization").status == "warning"


def test_blocked_active_device_fails(tmp_path: Path, project_root: Path) -> None:
    profile = load_usb_profile(project_root / "config/usb.yaml")
    profile["policy"]["blocked_vid_pid"] = ["046d:c52b"]
    assert not compare_usb(inventory(), profile).compatible


def test_plan_and_execution(tmp_path: Path, project_root: Path) -> None:
    plan = create_usb_configuration_plan(tmp_path / "build/rootfs", project_root / "config/usb.yaml")
    assert "usbutils" in plan.packages
    assert UsbConfigurator().execute(plan, dry_run=True) == ()
    written = UsbConfigurator().execute(plan)
    assert len(written) == 3
    assert "usbhid" in written[0].read_text()
    policy = json.loads(written[2].read_text())
    assert "smartcard" in policy["freerdp_redirectable"]


def test_block_rule_is_deterministic(tmp_path: Path, project_root: Path) -> None:
    profile = load_usb_profile(project_root / "config/usb.yaml")
    profile["policy"]["blocked_vid_pid"] = ["1234:abcd"]
    custom = tmp_path / "usb.yaml"
    custom.write_text(__import__("yaml").safe_dump(profile, sort_keys=False), encoding="utf-8")
    plan = create_usb_configuration_plan(tmp_path / "build/rootfs", custom)
    assert 'ATTR{idVendor}=="1234"' in plan.files[1][1]
    assert 'ATTR{authorized}="0"' in plan.files[1][1]


def test_unsafe_rootfs_rejected(project_root: Path) -> None:
    with pytest.raises(UsbPeripheralError, match="Rootfs insegur"):
        create_usb_configuration_plan(Path("/"), project_root / "config/usb.yaml")


def test_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    plan = create_usb_configuration_plan(tmp_path / "build/rootfs", project_root / "config/usb.yaml")
    target = plan.rootfs / "etc/xaac/usb-policy.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "other")
    with pytest.raises(UsbPeripheralError, match="enllaç simbòlic"):
        UsbConfigurator().execute(plan)


def test_report_written_atomically(tmp_path: Path, project_root: Path) -> None:
    report = compare_usb(inventory(), load_usb_profile(project_root / "config/usb.yaml"))
    destination = tmp_path / "usb.json"
    write_usb_report(report, destination)
    assert json.loads(destination.read_text())["compatible"] is True
    assert not destination.with_suffix(".json.tmp").exists()


def test_report_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    report = compare_usb(inventory(), load_usb_profile(project_root / "config/usb.yaml"))
    destination = tmp_path / "usb.json"
    destination.symlink_to(tmp_path / "other")
    with pytest.raises(UsbPeripheralError):
        write_usb_report(report, destination)


def test_cli_parser_accepts_usb_commands(project_root: Path) -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["--root", str(project_root), "configure-usb", "--dry-run"])
    assert args.command == "configure-usb"


def test_cli_inspect_usb_json(monkeypatch: pytest.MonkeyPatch, project_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from xaac_thin_client_os.cli import main
    monkeypatch.setattr("xaac_thin_client_os.cli.UsbDetector.detect", lambda self: inventory())
    assert main(["--root", str(project_root), "--json", "inspect-usb"]) == 0
    assert json.loads(capsys.readouterr().out)["compatible"] is True
