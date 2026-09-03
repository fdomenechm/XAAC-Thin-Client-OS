from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaac_thin_client_os.hardware_inventory import (
    HardwareDetector,
    HardwareInventory,
    HardwareInventoryError,
    compare_hardware,
    load_hardware_profile,
    write_hardware_report,
)


def write(root: Path, relative: str, value: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def fake_wyse(root: Path) -> None:
    write(root, "sys/class/dmi/id/sys_vendor", "Dell Inc.\n")
    write(root, "sys/class/dmi/id/product_name", "Wyse 3040 Thin Client\n")
    write(root, "proc/cpuinfo", "".join(f"processor : {i}\nmodel name : Intel(R) Atom(TM) x5-Z8350 CPU\n" for i in range(4)))
    write(root, "proc/meminfo", "MemTotal:       2010000 kB\n")
    write(root, "proc/modules", "i915 123 0 - Live 0x0\n")
    write(root, "sys/class/block/mmcblk0/size", "15269888\n")
    write(root, "sys/class/block/mmcblk0p1/size", "1000\n")
    write(root, "sys/bus/pci/devices/0000:00:02.0/vendor", "0x8086\n")
    write(root, "sys/bus/pci/devices/0000:00:02.0/class", "0x030000\n")
    write(root, "sys/bus/pci/devices/0000:00:1b.0/vendor", "0x8086\n")
    write(root, "sys/bus/pci/devices/0000:00:1b.0/class", "0x040300\n")
    for index in range(3):
        write(root, f"sys/bus/pci/devices/0000:00:1{index}.0/class", "0x0c0320\n")
    write(root, "sys/bus/pci/devices/0000:00:15.0/class", "0x0c0330\n")
    (root / "sys/class/net/eno1").mkdir(parents=True)
    (root / "sys/class/net/lo").mkdir(parents=True)
    write(root, "sys/class/thermal/thermal_zone0/temp", "42000\n")
    (root / "sys/firmware/efi").mkdir(parents=True)


def inventory() -> HardwareInventory:
    return HardwareInventory(
        manufacturer="Dell Inc.", product_name="Wyse 3040 Thin Client",
        cpu_model="Intel(R) Atom(TM) x5-Z8350 CPU", cpu_cores=4,
        architecture="x86_64", memory_mib=1962, emmc_devices=("mmcblk0",),
        emmc_total_mib=7456, intel_graphics=True, i915_loaded=True,
        ethernet_interfaces=("eno1",), audio_present=True, usb2_controllers=3,
        usb3_controllers=1, uefi=True, temperature_sensors=("thermal_zone0",),
    )


def test_detects_complete_wyse_inventory(tmp_path: Path) -> None:
    fake_wyse(tmp_path)
    found = HardwareDetector(root=tmp_path, machine=lambda: "x86_64").detect()
    assert found.manufacturer == "Dell Inc."
    assert found.cpu_cores == 4
    assert found.emmc_devices == ("mmcblk0",)
    assert found.emmc_total_mib == 7456
    assert found.intel_graphics and found.i915_loaded and found.uefi
    assert found.ethernet_interfaces == ("eno1",)
    assert found.usb2_controllers == 3 and found.usb3_controllers == 1


def test_missing_files_produce_safe_empty_inventory(tmp_path: Path) -> None:
    found = HardwareDetector(root=tmp_path, machine=lambda: "x86_64").detect()
    assert found.manufacturer is None
    assert found.memory_mib == 0
    assert found.emmc_devices == ()


def test_profile_load_and_compatible_comparison(project_root: Path) -> None:
    profile = load_hardware_profile(project_root / "config/hardware.yaml")
    report = compare_hardware(inventory(), profile)
    assert report.compatible
    assert all(check.status in {"pass", "warning"} for check in report.checks)


def test_absent_required_hardware_is_incompatible(project_root: Path) -> None:
    profile = load_hardware_profile(project_root / "config/hardware.yaml")
    bad = inventory().__class__(**{**inventory().to_dict(), "emmc_devices": (), "emmc_total_mib": 0, "ethernet_interfaces": ()})
    report = compare_hardware(bad, profile)
    assert not report.compatible
    assert {item.name for item in report.checks if item.status == "fail"} >= {"emmc", "ethernet"}


def test_temperature_sensor_is_optional(project_root: Path) -> None:
    profile = load_hardware_profile(project_root / "config/hardware.yaml")
    data = inventory().to_dict(); data["temperature_sensors"] = []
    value = HardwareInventory(**{**data, "emmc_devices": tuple(data["emmc_devices"]), "ethernet_interfaces": tuple(data["ethernet_interfaces"]), "temperature_sensors": ()})
    report = compare_hardware(value, profile)
    assert report.compatible
    assert next(item for item in report.checks if item.name == "temperature").status == "warning"


def test_invalid_profile_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "hardware.yaml"; path.write_text("schema_version: 99\n", encoding="utf-8")
    with pytest.raises(HardwareInventoryError, match="invàlid"):
        load_hardware_profile(path)


def test_report_is_written_atomically(tmp_path: Path, project_root: Path) -> None:
    report = compare_hardware(inventory(), load_hardware_profile(project_root / "config/hardware.yaml"))
    path = tmp_path / "reports/hardware.json"
    write_hardware_report(report, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["profile"] == "wyse3040"
    assert payload["compatible"] is True
    assert not path.with_suffix(".json.tmp").exists()
