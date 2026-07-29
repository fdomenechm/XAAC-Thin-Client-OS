"""eMMC detection, validation and rootfs configuration for Dell Wyse 3040."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class EmmcSupportError(RuntimeError):
    """Raised when eMMC detection or configuration cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class EmmcDevice:
    name: str
    size_mib: int
    removable: bool
    rotational: bool
    logical_block_size: int
    discard_max_bytes: int
    device_type: str | None
    cid: str | None

    @property
    def trim_supported(self) -> bool:
        return self.discard_max_bytes > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": f"/dev/{self.name}",
            "size_mib": self.size_mib,
            "removable": self.removable,
            "rotational": self.rotational,
            "logical_block_size": self.logical_block_size,
            "discard_max_bytes": self.discard_max_bytes,
            "trim_supported": self.trim_supported,
            "device_type": self.device_type,
            "cid": self.cid,
        }


@dataclass(frozen=True, slots=True)
class EmmcCheck:
    name: str
    status: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "expected": self.expected, "actual": self.actual}


@dataclass(frozen=True, slots=True)
class EmmcReport:
    profile: str
    compatible: bool
    selected_device: EmmcDevice | None
    devices: tuple[EmmcDevice, ...]
    loaded_modules: tuple[str, ...]
    checks: tuple[EmmcCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "compatible": self.compatible,
            "selected_device": self.selected_device.to_dict() if self.selected_device else None,
            "devices": [device.to_dict() for device in self.devices],
            "loaded_modules": list(self.loaded_modules),
            "checks": [check.to_dict() for check in self.checks],
        }


class EmmcDetector:
    """Read eMMC properties from a Linux sysfs tree without requiring root."""

    def __init__(self, *, root: Path = Path("/")) -> None:
        self.root = root

    def _read(self, relative: str) -> str | None:
        try:
            value = (self.root / relative.lstrip("/")).read_text(encoding="utf-8", errors="replace").strip()
        except (OSError, UnicodeError):
            return None
        return value or None

    def _integer(self, relative: str, default: int = 0) -> int:
        value = self._read(relative)
        try:
            return int(value) if value is not None else default
        except ValueError:
            return default

    def detect(self) -> tuple[tuple[EmmcDevice, ...], tuple[str, ...]]:
        block_root = self.root / "sys/class/block"
        devices: list[EmmcDevice] = []
        if block_root.is_dir():
            for entry in sorted(block_root.iterdir(), key=lambda item: item.name):
                if not re.fullmatch(r"mmcblk\d+", entry.name):
                    continue
                name = entry.name
                sectors = self._integer(f"sys/class/block/{name}/size")
                devices.append(
                    EmmcDevice(
                        name=name,
                        size_mib=sectors * 512 // (1024 * 1024),
                        removable=bool(self._integer(f"sys/class/block/{name}/removable")),
                        rotational=bool(self._integer(f"sys/class/block/{name}/queue/rotational")),
                        logical_block_size=self._integer(f"sys/class/block/{name}/queue/logical_block_size", 512),
                        discard_max_bytes=self._integer(f"sys/class/block/{name}/queue/discard_max_bytes"),
                        device_type=self._read(f"sys/class/block/{name}/device/type"),
                        cid=self._read(f"sys/class/block/{name}/device/cid"),
                    )
                )
        modules_text = self._read("proc/modules") or ""
        modules = tuple(sorted({line.split(maxsplit=1)[0] for line in modules_text.splitlines() if line.strip()}))
        return tuple(devices), modules


def load_emmc_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EmmcSupportError(f"No s'ha pogut carregar el perfil eMMC: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("profile"), str):
        raise EmmcSupportError("Perfil eMMC invàlid o versió d'esquema no suportada")
    required = {"storage", "kernel", "trim", "mounts"}
    if not required.issubset(raw) or not all(isinstance(raw[key], dict) for key in required):
        raise EmmcSupportError("El perfil eMMC no conté totes les seccions obligatòries")
    return raw


def compare_emmc(devices: tuple[EmmcDevice, ...], modules: tuple[str, ...], profile: dict[str, Any]) -> EmmcReport:
    storage = profile["storage"]
    kernel = profile["kernel"]
    trim = profile["trim"]
    prefix = str(storage.get("device_prefix", "mmcblk"))
    candidates = tuple(device for device in devices if device.name.startswith(prefix))
    selected = max(candidates, key=lambda device: device.size_mib, default=None)
    checks: list[EmmcCheck] = []

    def add(name: str, ok: bool, expected: object, actual: object, *, optional: bool = False) -> None:
        checks.append(EmmcCheck(name, "pass" if ok else ("warning" if optional else "fail"), str(expected), str(actual)))

    add("device", selected is not None, f"/dev/{prefix}N", selected.name if selected else "absent")
    if selected is not None:
        add("capacity", selected.size_mib >= int(storage.get("minimum_mib", 0)), f">={storage.get('minimum_mib')} MiB", f"{selected.size_mib} MiB")
        add("non-removable", not selected.removable or not storage.get("required_non_removable", True), "non-removable", selected.removable)
        add("non-rotational", not selected.rotational or not storage.get("required_non_rotational", True), "non-rotational", selected.rotational)
        add("sector-size", selected.logical_block_size == int(storage.get("sector_size", 512)), storage.get("sector_size", 512), selected.logical_block_size)
        add("trim", selected.discard_max_bytes >= int(trim.get("minimum_discard_bytes", 1)) or not trim.get("required", True), f">={trim.get('minimum_discard_bytes')} discard bytes", selected.discard_max_bytes)
    required_modules = kernel.get("required_any_modules", [])
    module_ok = isinstance(required_modules, list) and any(isinstance(item, str) and item in modules for item in required_modules)
    add("kernel-driver", module_ok, f"one of {required_modules}", modules)
    compatible = not any(check.status == "fail" for check in checks)
    return EmmcReport(str(profile["profile"]), compatible, selected, devices, modules, tuple(checks))


@dataclass(frozen=True, slots=True)
class EmmcConfigurationPlan:
    rootfs: Path
    modules: tuple[str, ...]
    timer_name: str
    files: tuple[tuple[PurePosixPath, str, int], ...]
    enable_link: PurePosixPath

    def to_manifest(self) -> dict[str, object]:
        return {
            "modules": list(self.modules),
            "timer": self.timer_name,
            "files": [str(path) for path, _, _ in self.files],
            "enable_link": str(self.enable_link),
        }


@dataclass(frozen=True, slots=True)
class EmmcConfigurationResult:
    plan: EmmcConfigurationPlan
    executed: bool
    files_written: tuple[Path, ...]


def create_emmc_configuration_plan(rootfs: Path, profile_path: Path) -> EmmcConfigurationPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise EmmcSupportError(f"Rootfs insegur: {root}")
    profile = load_emmc_profile(profile_path)
    raw_modules = profile["kernel"].get("required_any_modules", [])
    if not isinstance(raw_modules, list) or not raw_modules or not all(isinstance(item, str) and re.fullmatch(r"[a-zA-Z0-9_]+", item) for item in raw_modules):
        raise EmmcSupportError("La llista de mòduls eMMC no és vàlida")
    modules = tuple(dict.fromkeys(raw_modules))
    timer = profile["trim"].get("timer")
    if not isinstance(timer, str) or not re.fullmatch(r"[a-zA-Z0-9_.@-]+\.timer", timer):
        raise EmmcSupportError("El timer de TRIM no és vàlid")
    modules_content = "# XAAC Thin Client OS - eMMC drivers\n" + "\n".join(modules) + "\n"
    policy_content = (
        "# XAAC Thin Client OS - eMMC policy\n"
        "# Use periodic fstrim instead of continuous discard to reduce mount-time coupling.\n"
        "XAAC_EMMC_DEVICE_PREFIX=mmcblk\n"
        "XAAC_EMMC_MOUNTS=PARTLABEL\n"
        "XAAC_EMMC_TRIM=periodic\n"
    )
    files = (
        (PurePosixPath("/etc/modules-load.d/xaac-emmc.conf"), modules_content, 0o644),
        (PurePosixPath("/etc/xaac/emmc.conf"), policy_content, 0o644),
    )
    return EmmcConfigurationPlan(root, modules, timer, files, PurePosixPath(f"/etc/systemd/system/timers.target.wants/{timer}"))


class EmmcConfigurator:
    def __init__(self, *, unit_exists: Callable[[Path], bool] | None = None) -> None:
        self._unit_exists = unit_exists or Path.exists

    @staticmethod
    def _target(rootfs: Path, relative: PurePosixPath) -> Path:
        return rootfs / str(relative).lstrip("/")

    @staticmethod
    def _write_atomic(path: Path, content: str, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise EmmcSupportError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        temporary.replace(path)

    def execute(self, plan: EmmcConfigurationPlan, *, dry_run: bool = False) -> EmmcConfigurationResult:
        if dry_run:
            return EmmcConfigurationResult(plan, False, ())
        written: list[Path] = []
        for relative, content, mode in plan.files:
            target = self._target(plan.rootfs, relative)
            self._write_atomic(target, content, mode)
            written.append(target)
        unit = plan.rootfs / "usr/lib/systemd/system" / plan.timer_name
        if not self._unit_exists(unit):
            alternate = plan.rootfs / "lib/systemd/system" / plan.timer_name
            if not self._unit_exists(alternate):
                raise EmmcSupportError(f"No existeix la unitat systemd requerida: {plan.timer_name}")
            unit = alternate
        link = self._target(plan.rootfs, plan.enable_link)
        link.parent.mkdir(parents=True, exist_ok=True)
        expected = Path("/") / unit.relative_to(plan.rootfs)
        if link.is_symlink():
            if Path(os.readlink(link)) != expected:
                raise EmmcSupportError(f"L'enllaç existent no apunta a {expected}: {link}")
        elif link.exists():
            raise EmmcSupportError(f"La ruta d'activació ja existeix i no és un enllaç: {link}")
        else:
            link.symlink_to(expected)
        written.append(link)
        return EmmcConfigurationResult(plan, True, tuple(written))


def write_emmc_report(report: EmmcReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise EmmcSupportError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(path)
