"""USB controller and peripheral inventory and policy for Dell Wyse 3040."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class UsbPeripheralError(RuntimeError):
    """Raised when USB inspection or configuration is invalid or unsafe."""


_CLASS_NAMES = {
    "03": "hid",
    "08": "storage",
    "0b": "smartcard",
    "07": "printer",
    "0e": "camera",
}


@dataclass(frozen=True, slots=True)
class UsbDevice:
    sys_name: str
    vendor_id: str
    product_id: str
    manufacturer: str
    product: str
    usb_version: str
    speed_mbps: int | None
    classes: tuple[str, ...]
    authorized: bool

    @property
    def vid_pid(self) -> str:
        return f"{self.vendor_id}:{self.product_id}"

    def to_dict(self) -> dict[str, object]:
        return {
            "sys_name": self.sys_name,
            "vendor_id": self.vendor_id,
            "product_id": self.product_id,
            "vid_pid": self.vid_pid,
            "manufacturer": self.manufacturer,
            "product": self.product,
            "usb_version": self.usb_version,
            "speed_mbps": self.speed_mbps,
            "classes": list(self.classes),
            "authorized": self.authorized,
        }


@dataclass(frozen=True, slots=True)
class UsbInventory:
    usb2_controllers: int
    usb3_controllers: int
    devices: tuple[UsbDevice, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "usb2_controllers": self.usb2_controllers,
            "usb3_controllers": self.usb3_controllers,
            "devices": [device.to_dict() for device in self.devices],
        }


@dataclass(frozen=True, slots=True)
class UsbCheck:
    name: str
    status: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "expected": self.expected, "actual": self.actual}


@dataclass(frozen=True, slots=True)
class UsbReport:
    profile: str
    compatible: bool
    inventory: UsbInventory
    checks: tuple[UsbCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "compatible": self.compatible,
            "inventory": self.inventory.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
        }


class UsbDetector:
    """Read USB devices from sysfs without requiring elevated privileges."""

    def __init__(self, *, root: Path = Path("/")) -> None:
        self.root = root

    @staticmethod
    def _read(path: Path, default: str = "") -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except (OSError, UnicodeError):
            return default

    def detect(self) -> UsbInventory:
        base = self.root / "sys/bus/usb/devices"
        if not base.is_dir():
            return UsbInventory(0, 0, ())
        usb2 = 0
        usb3 = 0
        devices: list[UsbDevice] = []
        for item in sorted(base.iterdir(), key=lambda p: p.name):
            version = self._read(item / "version")
            if item.name.startswith("usb"):
                if version.startswith("3"):
                    usb3 += 1
                elif version:
                    usb2 += 1
                continue
            vendor = self._read(item / "idVendor").lower()
            product_id = self._read(item / "idProduct").lower()
            if not vendor or not product_id:
                continue
            classes: set[str] = set()
            device_class = self._read(item / "bDeviceClass").lower().zfill(2)
            if device_class in _CLASS_NAMES:
                classes.add(_CLASS_NAMES[device_class])
            for interface in sorted(base.glob(f"{item.name}:*")):
                interface_class = self._read(interface / "bInterfaceClass").lower().zfill(2)
                if interface_class in _CLASS_NAMES:
                    classes.add(_CLASS_NAMES[interface_class])
            speed_text = self._read(item / "speed")
            try:
                speed = int(float(speed_text)) if speed_text else None
            except ValueError:
                speed = None
            devices.append(
                UsbDevice(
                    item.name,
                    vendor,
                    product_id,
                    self._read(item / "manufacturer"),
                    self._read(item / "product"),
                    version,
                    speed,
                    tuple(sorted(classes)),
                    self._read(item / "authorized", "1") != "0",
                )
            )
        return UsbInventory(usb2, usb3, tuple(devices))


def load_usb_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UsbPeripheralError(f"No s'ha pogut carregar el perfil USB: {exc}") from exc
    required = ("controllers", "classes", "policy", "configuration", "packages")
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != 1
        or not isinstance(raw.get("profile"), str)
        or not all(isinstance(raw.get(key), dict) for key in required[:-1])
        or not isinstance(raw.get("packages"), list)
    ):
        raise UsbPeripheralError("Perfil USB invàlid o esquema no suportat")
    policy = raw["policy"]
    if policy.get("default_action") not in {"allow", "deny"}:
        raise UsbPeripheralError("L'acció USB predeterminada ha de ser allow o deny")
    for key in ("authorized_vid_pid", "blocked_vid_pid"):
        values = policy.get(key, [])
        if not isinstance(values, list) or any(not _valid_vid_pid(str(value)) for value in values):
            raise UsbPeripheralError(f"Llista {key} invàlida")
    return raw


def _valid_vid_pid(value: str) -> bool:
    parts = value.lower().split(":")
    return len(parts) == 2 and all(len(part) == 4 and all(c in "0123456789abcdef" for c in part) for part in parts)


def compare_usb(inventory: UsbInventory, profile: dict[str, Any]) -> UsbReport:
    checks: list[UsbCheck] = []

    def add(name: str, ok: bool, expected: object, actual: object, *, warning: bool = False) -> None:
        checks.append(UsbCheck(name, "pass" if ok else ("warning" if warning else "fail"), str(expected), str(actual)))

    controllers = profile["controllers"]
    add("usb2-controllers", inventory.usb2_controllers >= int(controllers.get("minimum_usb2", 0)), f">={controllers.get('minimum_usb2', 0)}", inventory.usb2_controllers)
    add("usb3-controllers", inventory.usb3_controllers >= int(controllers.get("minimum_usb3", 0)), f">={controllers.get('minimum_usb3', 0)}", inventory.usb3_controllers)
    present = {class_name for device in inventory.devices for class_name in device.classes}
    for class_name in profile["classes"].get("required", []):
        add(f"class-{class_name}", class_name in present, class_name, sorted(present) or "absent")
    for class_name in profile["classes"].get("optional", []):
        add(f"class-{class_name}", class_name in present, class_name, sorted(present) or "absent", warning=True)
    blocked = {str(value).lower() for value in profile["policy"].get("blocked_vid_pid", [])}
    active_blocked = sorted(device.vid_pid for device in inventory.devices if device.authorized and device.vid_pid in blocked)
    add("blocked-devices", not active_blocked, "none authorized", active_blocked or "none")
    unauthorized = sorted(device.vid_pid for device in inventory.devices if not device.authorized)
    add("device-authorization", not unauthorized, "all detected devices authorized", unauthorized or "all", warning=True)
    return UsbReport(str(profile["profile"]), not any(check.status == "fail" for check in checks), inventory, tuple(checks))


@dataclass(frozen=True, slots=True)
class UsbConfigurationPlan:
    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]
    packages: tuple[str, ...]

    def to_manifest(self) -> dict[str, object]:
        return {"files": [str(item[0]) for item in self.files], "packages": list(self.packages)}


def create_usb_configuration_plan(rootfs: Path, profile_path: Path) -> UsbConfigurationPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise UsbPeripheralError(f"Rootfs insegur: {root}")
    profile = load_usb_profile(profile_path)
    cfg = profile["configuration"]
    policy = profile["policy"]
    modules = tuple(str(value) for value in cfg.get("modules", []))
    rules: list[str] = ["# Managed by XAAC Thin Client OS"]
    for vid_pid in sorted(str(value).lower() for value in policy.get("blocked_vid_pid", [])):
        vendor, product = vid_pid.split(":")
        rules.append(f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vendor}", ATTR{{idProduct}}=="{product}", ATTR{{authorized}}="0"')
    if policy.get("default_action") == "deny":
        for vid_pid in sorted(str(value).lower() for value in policy.get("authorized_vid_pid", [])):
            vendor, product = vid_pid.split(":")
            rules.append(f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vendor}", ATTR{{idProduct}}=="{product}", ATTR{{authorized}}="1"')
    policy_json = json.dumps(
        {
            "default_action": policy["default_action"],
            "authorized_vid_pid": sorted(str(value).lower() for value in policy.get("authorized_vid_pid", [])),
            "blocked_vid_pid": sorted(str(value).lower() for value in policy.get("blocked_vid_pid", [])),
            "removable_storage": policy.get("removable_storage", "controlled"),
            "freerdp_redirectable": sorted(str(value) for value in policy.get("freerdp_redirectable", [])),
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    files = (
        (PurePosixPath(str(cfg["modules_file"])), "\n".join(modules) + "\n", 0o644),
        (PurePosixPath(str(cfg["udev_rules_file"])), "\n".join(rules) + "\n", 0o644),
        (PurePosixPath(str(cfg["policy_file"])), policy_json, 0o644),
    )
    return UsbConfigurationPlan(root, files, tuple(str(value) for value in profile["packages"]))


class UsbConfigurator:
    def execute(self, plan: UsbConfigurationPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for rel, content, mode in plan.files:
            target = plan.rootfs / str(rel).lstrip("/")
            if target.is_symlink():
                raise UsbPeripheralError(f"No s'escriu sobre un enllaç simbòlic: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".tmp")
            temp.write_text(content, encoding="utf-8")
            temp.chmod(mode)
            temp.replace(target)
            written.append(target)
        return tuple(written)


def write_usb_report(report: UsbReport, destination: Path) -> None:
    if destination.is_symlink():
        raise UsbPeripheralError(f"No s'escriu sobre un enllaç simbòlic: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(destination)
