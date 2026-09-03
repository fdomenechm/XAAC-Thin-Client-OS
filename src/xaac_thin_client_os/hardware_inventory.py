"""Dell Wyse 3040 hardware inventory and profile comparison."""
from __future__ import annotations

import json
import platform
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class HardwareInventoryError(RuntimeError):
    """Raised when the hardware profile or inventory is invalid."""


@dataclass(frozen=True, slots=True)
class HardwareInventory:
    manufacturer: str | None
    product_name: str | None
    cpu_model: str | None
    cpu_cores: int
    architecture: str
    memory_mib: int
    emmc_devices: tuple[str, ...]
    emmc_total_mib: int
    intel_graphics: bool
    i915_loaded: bool
    ethernet_interfaces: tuple[str, ...]
    audio_present: bool
    usb2_controllers: int
    usb3_controllers: int
    uefi: bool
    temperature_sensors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "manufacturer": self.manufacturer,
            "product_name": self.product_name,
            "cpu_model": self.cpu_model,
            "cpu_cores": self.cpu_cores,
            "architecture": self.architecture,
            "memory_mib": self.memory_mib,
            "emmc_devices": list(self.emmc_devices),
            "emmc_total_mib": self.emmc_total_mib,
            "intel_graphics": self.intel_graphics,
            "i915_loaded": self.i915_loaded,
            "ethernet_interfaces": list(self.ethernet_interfaces),
            "audio_present": self.audio_present,
            "usb2_controllers": self.usb2_controllers,
            "usb3_controllers": self.usb3_controllers,
            "uefi": self.uefi,
            "temperature_sensors": list(self.temperature_sensors),
        }


@dataclass(frozen=True, slots=True)
class HardwareCheck:
    name: str
    status: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "expected": self.expected, "actual": self.actual}


@dataclass(frozen=True, slots=True)
class HardwareCompatibilityReport:
    profile: str
    compatible: bool
    checks: tuple[HardwareCheck, ...]
    inventory: HardwareInventory

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "compatible": self.compatible,
            "checks": [check.to_dict() for check in self.checks],
            "inventory": self.inventory.to_dict(),
        }


class HardwareDetector:
    """Collect an inventory from Linux procfs and sysfs without requiring root."""

    def __init__(self, *, root: Path = Path("/"), machine: Callable[[], str] = platform.machine) -> None:
        self.root = root
        self.machine = machine

    def _read(self, relative: str) -> str | None:
        try:
            value = (self.root / relative.lstrip("/")).read_text(encoding="utf-8", errors="replace").strip()
        except (OSError, UnicodeError):
            return None
        return value or None

    def detect(self) -> HardwareInventory:
        cpuinfo = self._read("proc/cpuinfo") or ""
        meminfo = self._read("proc/meminfo") or ""
        modules = self._read("proc/modules") or ""
        cpu_model = next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines() if line.lower().startswith("model name") and ":" in line), None)
        cpu_cores = sum(1 for line in cpuinfo.splitlines() if line.lower().startswith("processor") and ":" in line)
        mem_match = re.search(r"^MemTotal:\s+(\d+)\s+kB$", meminfo, re.MULTILINE)
        memory_mib = int(mem_match.group(1)) // 1024 if mem_match else 0

        block_root = self.root / "sys/class/block"
        emmc: list[str] = []
        emmc_total = 0
        if block_root.is_dir():
            for device in sorted(block_root.glob("mmcblk*")):
                if "p" in device.name.removeprefix("mmcblk"):
                    continue
                sectors = self._read(f"sys/class/block/{device.name}/size")
                if sectors and sectors.isdigit():
                    emmc.append(device.name)
                    emmc_total += int(sectors) * 512 // (1024 * 1024)

        pci_root = self.root / "sys/bus/pci/devices"
        intel_graphics = False
        audio_present = False
        usb2 = 0
        usb3 = 0
        if pci_root.is_dir():
            for device in pci_root.iterdir():
                vendor = self._read(f"sys/bus/pci/devices/{device.name}/vendor")
                klass = self._read(f"sys/bus/pci/devices/{device.name}/class")
                if vendor == "0x8086" and klass and klass.startswith("0x03"):
                    intel_graphics = True
                if klass and klass.startswith("0x04"):
                    audio_present = True
                if klass and klass.startswith("0x0c03"):
                    if klass.startswith(("0x0c0330", "0x0c0340")):
                        usb3 += 1
                    else:
                        usb2 += 1

        net_root = self.root / "sys/class/net"
        ethernet = tuple(sorted(item.name for item in net_root.iterdir() if item.name != "lo")) if net_root.is_dir() else ()
        thermal_root = self.root / "sys/class/thermal"
        sensors = tuple(sorted(item.name for item in thermal_root.glob("thermal_zone*") if self._read(f"sys/class/thermal/{item.name}/temp"))) if thermal_root.is_dir() else ()

        return HardwareInventory(
            manufacturer=self._read("sys/class/dmi/id/sys_vendor"),
            product_name=self._read("sys/class/dmi/id/product_name"),
            cpu_model=cpu_model,
            cpu_cores=cpu_cores,
            architecture=self.machine(),
            memory_mib=memory_mib,
            emmc_devices=tuple(emmc),
            emmc_total_mib=emmc_total,
            intel_graphics=intel_graphics,
            i915_loaded=bool(re.search(r"^i915\s", modules, re.MULTILINE)),
            ethernet_interfaces=ethernet,
            audio_present=audio_present,
            usb2_controllers=usb2,
            usb3_controllers=usb3,
            uefi=(self.root / "sys/firmware/efi").is_dir(),
            temperature_sensors=sensors,
        )


def load_hardware_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise HardwareInventoryError(f"No s'ha pogut carregar el perfil de maquinari: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("profile"), str):
        raise HardwareInventoryError("Perfil de maquinari invàlid o versió d'esquema no suportada")
    return raw


def _patterns_match(value: str | None, patterns: object) -> bool:
    return bool(value and isinstance(patterns, list) and any(isinstance(item, str) and item.lower() in value.lower() for item in patterns))


def compare_hardware(inventory: HardwareInventory, profile: dict[str, Any]) -> HardwareCompatibilityReport:
    checks: list[HardwareCheck] = []
    def add(name: str, ok: bool, expected: object, actual: object, *, optional: bool = False) -> None:
        status = "pass" if ok else ("warning" if optional else "fail")
        checks.append(HardwareCheck(name, status, str(expected), str(actual)))

    identity = profile.get("identity", {})
    cpu = profile.get("cpu", {})
    memory = profile.get("memory", {})
    storage = profile.get("storage", {})
    graphics = profile.get("graphics", {})
    network = profile.get("network", {})
    audio = profile.get("audio", {})
    usb = profile.get("usb", {})
    firmware = profile.get("firmware", {})
    sensors = profile.get("sensors", {})
    add("manufacturer", _patterns_match(inventory.manufacturer, identity.get("manufacturer_patterns")), identity.get("manufacturer_patterns"), inventory.manufacturer)
    add("product", _patterns_match(inventory.product_name, identity.get("product_patterns")), identity.get("product_patterns"), inventory.product_name)
    add("architecture", inventory.architecture in {cpu.get("architecture"), "amd64" if cpu.get("architecture") == "x86_64" else ""}, cpu.get("architecture"), inventory.architecture)
    add("cpu-model", _patterns_match(inventory.cpu_model, cpu.get("model_patterns")), cpu.get("model_patterns"), inventory.cpu_model)
    add("cpu-cores", inventory.cpu_cores >= int(cpu.get("minimum_cores", 0)), f">={cpu.get('minimum_cores')}", inventory.cpu_cores)
    add("memory", inventory.memory_mib >= int(memory.get("minimum_mib", 0)), f">={memory.get('minimum_mib')} MiB", f"{inventory.memory_mib} MiB")
    add("emmc", bool(inventory.emmc_devices) and inventory.emmc_total_mib >= int(storage.get("minimum_mib", 0)), f"mmc >= {storage.get('minimum_mib')} MiB", f"{inventory.emmc_devices} {inventory.emmc_total_mib} MiB")
    add("intel-graphics", inventory.intel_graphics, "Intel PCI graphics", inventory.intel_graphics)
    add("i915", inventory.i915_loaded, graphics.get("driver", "i915"), inventory.i915_loaded)
    add("ethernet", bool(inventory.ethernet_interfaces), "Ethernet interface", inventory.ethernet_interfaces)
    add("audio", inventory.audio_present or not audio.get("required", True), "audio controller", inventory.audio_present)
    add("usb2", inventory.usb2_controllers >= int(usb.get("minimum_usb2_controllers", 0)), f">={usb.get('minimum_usb2_controllers')} controllers", inventory.usb2_controllers)
    add("usb3", inventory.usb3_controllers >= 1, ">=1 controller", inventory.usb3_controllers)
    add("uefi", inventory.uefi or not firmware.get("uefi_required", True), "UEFI", inventory.uefi)
    add("temperature", bool(inventory.temperature_sensors), "sensor available", inventory.temperature_sensors, optional=bool(sensors.get("temperature_optional", True)))
    compatible = not any(item.status == "fail" for item in checks)
    return HardwareCompatibilityReport(str(profile["profile"]), compatible, tuple(checks), inventory)


def write_hardware_report(report: HardwareCompatibilityReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
