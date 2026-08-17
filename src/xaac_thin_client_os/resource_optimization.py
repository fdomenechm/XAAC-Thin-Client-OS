"""RAM and storage optimisation for resource-constrained thin clients."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class ResourceOptimizationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceInventory:
    total_memory_mib: int
    available_memory_mib: int
    swap_total_mib: int
    zram_devices: tuple[str, ...]
    root_free_mib: int
    root_mount_options: tuple[str, ...]
    journald_persistent: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "total_memory_mib": self.total_memory_mib,
            "available_memory_mib": self.available_memory_mib,
            "swap_total_mib": self.swap_total_mib,
            "zram_devices": list(self.zram_devices),
            "root_free_mib": self.root_free_mib,
            "root_mount_options": list(self.root_mount_options),
            "journald_persistent": self.journald_persistent,
        }


@dataclass(frozen=True, slots=True)
class ResourceCheck:
    name: str
    status: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True, slots=True)
class ResourceReport:
    profile: str
    compatible: bool
    inventory: ResourceInventory
    checks: tuple[ResourceCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "compatible": self.compatible,
            "inventory": self.inventory.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
        }


class ResourceDetector:
    def __init__(self, *, root: Path = Path("/")) -> None:
        self.root = root

    @staticmethod
    def _read(path: Path, default: str = "") -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return default

    def detect(self) -> ResourceInventory:
        values: dict[str, int] = {}
        for line in self._read(self.root / "proc/meminfo").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            try:
                values[key] = int(value.strip().split()[0]) // 1024
            except (ValueError, IndexError):
                pass
        zram = tuple(sorted(path.name for path in (self.root / "sys/block").glob("zram*")))
        free = 0
        stat = self.root / "__root_statvfs__"
        if stat.exists():
            try:
                free = int(self._read(stat).strip())
            except ValueError:
                pass
        elif self.root == Path("/"):
            try:
                fs = self.root.statvfs()
                free = (fs.f_bavail * fs.f_frsize) // (1024 * 1024)
            except OSError:
                pass
        options: tuple[str, ...] = ()
        for line in self._read(self.root / "proc/mounts").splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[1] == "/":
                options = tuple(parts[3].split(","))
                break
        persistent = (self.root / "var/log/journal").exists()
        return ResourceInventory(
            values.get("MemTotal", 0),
            values.get("MemAvailable", 0),
            values.get("SwapTotal", 0),
            zram,
            free,
            options,
            persistent,
        )


def load_resource_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ResourceOptimizationError(f"No s'ha pogut carregar el perfil de recursos: {exc}") from exc
    required = ("memory", "storage", "journald", "tmpfs", "cleanup", "services", "configuration")
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != 1
        or not isinstance(raw.get("profile"), str)
        or any(not isinstance(raw.get(key), dict) for key in required)
        or not isinstance(raw.get("packages"), list)
    ):
        raise ResourceOptimizationError("Perfil de recursos invàlid o esquema no suportat")
    percent = int(raw["memory"].get("zram", {}).get("size_percent", 0))
    if percent < 10 or percent > 100:
        raise ResourceOptimizationError("Percentatge de zram invàlid")
    if int(raw["journald"].get("runtime_max_use_mib", 0)) <= 0:
        raise ResourceOptimizationError("Límit de journald invàlid")
    if int(raw["tmpfs"].get("tmp_size_mib", 0)) <= 0:
        raise ResourceOptimizationError("Límit de /tmp invàlid")
    if not isinstance(raw["storage"].get("trim_timer"), bool):
        raise ResourceOptimizationError("storage.trim_timer ha de ser booleà")
    if not isinstance(raw["services"].get("disabled"), list) or not all(
        isinstance(unit, str) and unit for unit in raw["services"]["disabled"]
    ):
        raise ResourceOptimizationError("services.disabled ha de ser una llista d'unitats")
    return raw


def compare_resources(inv: ResourceInventory, profile: dict[str, Any]) -> ResourceReport:
    checks: list[ResourceCheck] = []

    def add(name: str, ok: bool, expected: object, actual: object, *, warning: bool = False) -> None:
        checks.append(
            ResourceCheck(
                name,
                "pass" if ok else ("warning" if warning else "fail"),
                str(expected),
                str(actual),
            )
        )

    minimum = int(profile["memory"]["minimum_total_mib"])
    add("memory-total", inv.total_memory_mib >= minimum, f">={minimum} MiB", f"{inv.total_memory_mib} MiB")
    zram_required = bool(profile["memory"]["zram"]["enabled"])
    add(
        "zram",
        bool(inv.zram_devices) or not zram_required,
        "present" if zram_required else "optional",
        inv.zram_devices or "absent",
        warning=True,
    )
    free = int(profile["storage"]["root_minimum_free_mib"])
    add("root-free-space", inv.root_free_mib >= free, f">={free} MiB", f"{inv.root_free_mib} MiB", warning=True)
    noatime = not profile["storage"].get("require_noatime", True) or "noatime" in inv.root_mount_options
    add("root-noatime", noatime, "noatime", inv.root_mount_options or "unknown", warning=True)
    volatile = profile["journald"].get("storage") == "volatile"
    add(
        "journald-storage",
        not (volatile and inv.journald_persistent),
        "volatile",
        "persistent" if inv.journald_persistent else "volatile",
        warning=True,
    )
    return ResourceReport(
        str(profile["profile"]),
        not any(check.status == "fail" for check in checks),
        inv,
        tuple(checks),
    )


@dataclass(frozen=True, slots=True)
class ResourceConfigurationPlan:
    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]
    disabled_services: tuple[str, ...]
    packages: tuple[str, ...]
    enabled_units: tuple[tuple[PurePosixPath, str], ...]

    def to_manifest(self) -> dict[str, object]:
        return {
            "files": [str(item[0]) for item in self.files],
            "disabled_services": list(self.disabled_services),
            "packages": list(self.packages),
            "enabled_units": [str(item[0]) for item in self.enabled_units],
        }


def create_resource_configuration_plan(rootfs: Path, profile_path: Path) -> ResourceConfigurationPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise ResourceOptimizationError(f"Rootfs insegur: {root}")
    profile = load_resource_profile(profile_path)
    config = profile["configuration"]
    zram = profile["memory"]["zram"]
    journal = profile["journald"]
    tmpfs = profile["tmpfs"]
    cleanup = profile["cleanup"]
    policy = json.dumps(
        {key: profile[key] for key in ("memory", "storage", "journald", "tmpfs", "cleanup", "services")},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    files = (
        (
            PurePosixPath(config["zram_generator_file"]),
            "[zram0]\n"
            f"zram-size = ram * {int(zram['size_percent'])} / 100\n"
            f"compression-algorithm = {zram['algorithm']}\n"
            f"swap-priority = {int(zram['priority'])}\n",
            0o644,
        ),
        (
            PurePosixPath(config["sysctl_file"]),
            f"vm.swappiness = {int(profile['memory']['swappiness'])}\n"
            "vm.page-cluster = 0\n"
            "vm.vfs_cache_pressure = 100\n",
            0o644,
        ),
        (
            PurePosixPath(config["journald_file"]),
            "[Journal]\n"
            f"Storage={str(journal['storage']).capitalize()}\n"
            f"RuntimeMaxUse={int(journal['runtime_max_use_mib'])}M\n"
            f"RuntimeKeepFree={int(journal['runtime_keep_free_mib'])}M\n"
            f"MaxFileSec={journal['max_file_sec']}\n"
            "Compress=yes\n",
            0o644,
        ),
        (
            PurePosixPath(config["tmp_mount_file"]),
            "[Mount]\n"
            f"Options=mode=1777,strictatime,nosuid,nodev,size={int(tmpfs['tmp_size_mib'])}M\n",
            0o644,
        ),
        (
            PurePosixPath(config["fstab_dropin"]),
            "# Reference policy used by the production installer.\n"
            "# Persistent ext4 filesystems must be mounted with noatime.\n",
            0o644,
        ),
        (
            PurePosixPath(config["tmpfiles_file"]),
            f"D /tmp 1777 root root {int(cleanup['age_days'])}d\n"
            f"D /var/tmp 1777 root root {int(cleanup['age_days'])}d\n",
            0o644,
        ),
        (PurePosixPath(config["policy_file"]), policy, 0o644),
    )
    enabled_units: list[tuple[PurePosixPath, str]] = [
        (PurePosixPath("/etc/systemd/system/local-fs.target.wants/tmp.mount"), "/lib/systemd/system/tmp.mount")
    ]
    if profile["storage"]["trim_timer"]:
        enabled_units.append(
            (PurePosixPath("/etc/systemd/system/timers.target.wants/fstrim.timer"), "/lib/systemd/system/fstrim.timer")
        )
    return ResourceConfigurationPlan(
        root,
        files,
        tuple(str(unit) for unit in profile["services"]["disabled"]),
        tuple(str(package) for package in profile["packages"]),
        tuple(enabled_units),
    )


class ResourceConfigurator:
    @staticmethod
    def _replace_symlink(target: Path, link_to: str) -> None:
        if target.exists() and not target.is_symlink():
            raise ResourceOptimizationError(f"Ruta systemd conflictiva: {target}")
        if target.is_symlink():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(link_to)

    def execute(self, plan: ResourceConfigurationPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        out: list[Path] = []
        for relative, content, mode in plan.files:
            target = plan.rootfs / str(relative).lstrip("/")
            if target.is_symlink():
                raise ResourceOptimizationError(f"No s'escriu sobre un enllaç simbòlic: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(mode)
            temporary.replace(target)
            out.append(target)
        unit_root = plan.rootfs / "etc/systemd/system"
        unit_root.mkdir(parents=True, exist_ok=True)
        for service in plan.disabled_services:
            target = unit_root / service
            self._replace_symlink(target, "/dev/null")
            out.append(target)
        for relative, link_to in plan.enabled_units:
            target = plan.rootfs / str(relative).lstrip("/")
            self._replace_symlink(target, link_to)
            out.append(target)
        return tuple(out)


def write_resource_report(report: ResourceReport, destination: Path) -> None:
    if destination.is_symlink():
        raise ResourceOptimizationError(f"No s'escriu sobre un enllaç simbòlic: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
