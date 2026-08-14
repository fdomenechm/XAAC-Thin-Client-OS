from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.device_inventory import (
    DeviceInventoryCollector,
    DeviceInventoryError,
    inventory_digest,
    load_device_inventory_profile,
)


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "device-inventory.yaml"
    path.write_text(Path("config/device-inventory.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    (root / "etc").mkdir(parents=True)
    (root / "etc/hostname").write_text("xaac-test\n")
    (root / "etc/machine-id").write_text("0123456789abcdef0123456789abcdef\n")
    (root / "etc/os-release").write_text('PRETTY_NAME="Debian GNU/Linux 13"\n')
    (root / "sys/class/dmi/id").mkdir(parents=True)
    (root / "sys/class/dmi/id/product_name").write_text("Wyse 3040\n")
    (root / "sys/class/dmi/id/product_serial").write_text("ABC123\n")
    return root


def test_profile_loads_complete_inventory() -> None:
    profile = load_device_inventory_profile(Path("config/device-inventory.yaml"))
    assert profile["inventory"]["include_packages"] is True
    assert "xaac-agent" in profile["xaac_packages"]


def test_profile_rejects_relative_output(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/device-inventory.yaml").read_text())
    data["paths"]["output"] = "inventory.json"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(DeviceInventoryError, match="insegura"):
        load_device_inventory_profile(path)


def test_collects_system_hardware_and_status(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "etc/xaac-agent").mkdir(parents=True)
    (root / "etc/xaac-agent/agent.ini").write_text("[agent]\nenabled = false\n")
    collector = DeviceInventoryCollector(root, _profile(tmp_path), now=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc))
    inventory = collector.collect()
    assert inventory["hardware"]["product_name"] == "Wyse 3040"
    assert inventory["system"]["hostname"] == "xaac-test"
    assert inventory["status"]["agent_configured"] is True
    assert inventory["sha256"] == inventory_digest(inventory)


def test_collects_sorted_installed_packages_and_xaac_versions(tmp_path: Path) -> None:
    root = _root(tmp_path)
    status = root / "var/lib/dpkg/status"
    status.parent.mkdir(parents=True)
    status.write_text("Package: zlib1g\nStatus: install ok installed\nArchitecture: amd64\nVersion: 1.3\n\nPackage: xaac-agent\nStatus: install ok installed\nArchitecture: amd64\nVersion: 1.0.0\n")
    inventory = DeviceInventoryCollector(root, _profile(tmp_path)).collect()
    assert [item["name"] for item in inventory["packages"]] == ["xaac-agent", "zlib1g"]
    assert inventory["xaac_versions"]["xaac-agent"] == "1.0.0"
    assert inventory["xaac_versions"]["xaac-thinclient"] is None


def test_collects_usb_peripherals(tmp_path: Path) -> None:
    root = _root(tmp_path)
    usb = root / "sys/bus/usb/devices/1-1"
    usb.mkdir(parents=True)
    (usb / "idVendor").write_text("1234\n")
    (usb / "idProduct").write_text("ABCD\n")
    (usb / "product").write_text("Smart Card Reader\n")
    inventory = DeviceInventoryCollector(root, _profile(tmp_path)).collect()
    assert inventory["peripherals"][0]["vendor_id"] == "1234"
    assert inventory["peripherals"][0]["product_id"] == "abcd"


def test_install_dry_run_does_not_write(tmp_path: Path) -> None:
    root = _root(tmp_path)
    paths = DeviceInventoryCollector(root, _profile(tmp_path)).install(dry_run=True)
    assert len(paths) == 3
    assert not paths[0].exists()


def test_install_writes_inventory_state_and_manifest(tmp_path: Path) -> None:
    root = _root(tmp_path)
    paths = DeviceInventoryCollector(root, _profile(tmp_path)).install()
    assert all(path.is_file() for path in paths)
    assert json.loads(paths[1].read_text())["status"] == "collected"
    assert "peripherals" in json.loads(paths[2].read_text())["sections"]


def test_install_is_idempotent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    collector = DeviceInventoryCollector(root, _profile(tmp_path), now=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc))
    collector.install()
    first = (root / "var/lib/xaac-agent/inventory/inventory.json").read_text()
    collector.install()
    assert (root / "var/lib/xaac-agent/inventory/inventory.json").read_text() == first


def test_install_rejects_symlink_destination(tmp_path: Path) -> None:
    root = _root(tmp_path)
    destination = root / "var/lib/xaac-agent/inventory/inventory.json"
    destination.parent.mkdir(parents=True)
    destination.symlink_to("/tmp/unsafe")
    with pytest.raises(DeviceInventoryError, match="enllaç simbòlic"):
        DeviceInventoryCollector(root, _profile(tmp_path)).install()


def test_cli_exposes_inventory_command() -> None:
    args = build_parser().parse_args(["collect-device-inventory", "--dry-run"])
    assert args.command == "collect-device-inventory"
    assert args.dry_run is True
