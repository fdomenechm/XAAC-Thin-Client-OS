"""Intel i915 graphics detection and rootfs configuration for Dell Wyse 3040."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class IntelGraphicsError(RuntimeError):
    """Raised when graphics inspection or configuration is unsafe."""


@dataclass(frozen=True, slots=True)
class Connector:
    name: str
    status: str
    modes: tuple[str, ...]
    enabled: bool

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "status": self.status, "modes": list(self.modes), "enabled": self.enabled}


@dataclass(frozen=True, slots=True)
class GraphicsInventory:
    modules: tuple[str, ...]
    pci_vendors: tuple[str, ...]
    connectors: tuple[Connector, ...]
    kernel_command_line: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GraphicsCheck:
    name: str
    status: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "expected": self.expected, "actual": self.actual}


@dataclass(frozen=True, slots=True)
class GraphicsReport:
    profile: str
    compatible: bool
    inventory: GraphicsInventory
    checks: tuple[GraphicsCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "compatible": self.compatible,
            "modules": list(self.inventory.modules),
            "pci_vendors": list(self.inventory.pci_vendors),
            "kernel_command_line": list(self.inventory.kernel_command_line),
            "connectors": [item.to_dict() for item in self.inventory.connectors],
            "checks": [item.to_dict() for item in self.checks],
        }


class IntelGraphicsDetector:
    def __init__(self, *, root: Path = Path("/")) -> None:
        self.root = root

    def _read(self, relative: str) -> str | None:
        try:
            value = (self.root / relative.lstrip("/")).read_text(encoding="utf-8", errors="replace").strip()
        except (OSError, UnicodeError):
            return None
        return value or None

    def detect(self) -> GraphicsInventory:
        modules_text = self._read("proc/modules") or ""
        modules = tuple(sorted({line.split(maxsplit=1)[0] for line in modules_text.splitlines() if line.strip()}))
        vendors: set[str] = set()
        pci_root = self.root / "sys/bus/pci/devices"
        if pci_root.is_dir():
            for entry in pci_root.iterdir():
                vendor = self._read(f"sys/bus/pci/devices/{entry.name}/vendor")
                klass = self._read(f"sys/bus/pci/devices/{entry.name}/class")
                if vendor and klass and klass.lower().startswith("0x03"):
                    vendors.add(vendor.lower().removeprefix("0x"))
        connectors: list[Connector] = []
        drm_root = self.root / "sys/class/drm"
        if drm_root.is_dir():
            for entry in sorted(drm_root.iterdir(), key=lambda item: item.name):
                if "-" not in entry.name or entry.name.endswith("renderD128"):
                    continue
                status = self._read(f"sys/class/drm/{entry.name}/status") or "unknown"
                modes_text = self._read(f"sys/class/drm/{entry.name}/modes") or ""
                enabled = (self._read(f"sys/class/drm/{entry.name}/enabled") or "disabled") == "enabled"
                connectors.append(Connector(entry.name, status, tuple(line for line in modes_text.splitlines() if line), enabled))
        cmdline = tuple((self._read("proc/cmdline") or "").split())
        return GraphicsInventory(modules, tuple(sorted(vendors)), tuple(connectors), cmdline)


def load_graphics_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise IntelGraphicsError(f"No s'ha pogut carregar el perfil gràfic: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("profile"), str):
        raise IntelGraphicsError("Perfil gràfic invàlid o versió d'esquema no suportada")
    if not all(isinstance(raw.get(key), dict) for key in ("driver", "outputs", "modes", "configuration")):
        raise IntelGraphicsError("El perfil gràfic no conté totes les seccions obligatòries")
    return raw


def compare_graphics(inventory: GraphicsInventory, profile: dict[str, Any]) -> GraphicsReport:
    driver, outputs, modes = profile["driver"], profile["outputs"], profile["modes"]
    checks: list[GraphicsCheck] = []
    def add(name: str, ok: bool, expected: object, actual: object, *, warning: bool = False) -> None:
        checks.append(GraphicsCheck(name, "pass" if ok else ("warning" if warning else "fail"), str(expected), str(actual)))
    module = str(driver.get("module", "i915"))
    add("driver", module in inventory.modules, module, inventory.modules)
    vendor = str(driver.get("pci_vendor", "8086")).lower()
    add("intel-gpu", vendor in inventory.pci_vendors, vendor, inventory.pci_vendors)
    forbidden = tuple(str(item) for item in driver.get("forbidden_kernel_parameters", []))
    present_forbidden = tuple(item for item in inventory.kernel_command_line if item in forbidden)
    add("kernel-parameters", not present_forbidden, f"absence of {forbidden}", present_forbidden or "none")
    prefixes = tuple(str(item) for item in outputs.get("connector_prefixes", []))
    matching = tuple(item for item in inventory.connectors if any(prefix.lower() in item.name.lower() for prefix in prefixes))
    add("connectors", len(matching) >= int(outputs.get("minimum_connectors", 0)), f">={outputs.get('minimum_connectors')}", len(matching))
    connected = tuple(item for item in matching if item.status == "connected")
    allow_headless = bool(outputs.get("allow_headless", False))
    add("connected-output", bool(connected) or allow_headless, "connected output or headless allowed", len(connected), warning=allow_headless)
    minimum_width, minimum_height = int(modes.get("minimum_width", 0)), int(modes.get("minimum_height", 0))
    valid_mode = any(_mode_meets(mode, minimum_width, minimum_height) for item in connected for mode in item.modes)
    add("display-mode", valid_mode or (allow_headless and not connected), f">={minimum_width}x{minimum_height}", [mode for item in connected for mode in item.modes], warning=allow_headless and not connected)
    return GraphicsReport(str(profile["profile"]), not any(item.status == "fail" for item in checks), inventory, tuple(checks))


def _mode_meets(mode: str, width: int, height: int) -> bool:
    match = re.fullmatch(r"(\d+)x(\d+)(?:i)?", mode)
    return bool(match and int(match.group(1)) >= width and int(match.group(2)) >= height)


@dataclass(frozen=True, slots=True)
class GraphicsConfigurationPlan:
    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]
    firmware_packages: tuple[str, ...]

    def to_manifest(self) -> dict[str, object]:
        return {"files": [str(item[0]) for item in self.files], "firmware_packages": list(self.firmware_packages)}


def create_graphics_configuration_plan(rootfs: Path, profile_path: Path) -> GraphicsConfigurationPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise IntelGraphicsError(f"Rootfs insegur: {root}")
    profile = load_graphics_profile(profile_path)
    module = profile["driver"].get("module")
    if not isinstance(module, str) or not re.fullmatch(r"[A-Za-z0-9_]+", module):
        raise IntelGraphicsError("Mòdul gràfic invàlid")
    packages = profile["driver"].get("firmware_packages", [])
    if not isinstance(packages, list) or not all(isinstance(item, str) and re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", item) for item in packages):
        raise IntelGraphicsError("Paquets de firmware invàlids")
    files = (
        (PurePosixPath(str(profile["configuration"]["modules_file"])), f"# XAAC Intel graphics\n{module}\n", 0o644),
        (PurePosixPath(str(profile["configuration"]["modprobe_file"])), "# XAAC Intel graphics: kernel mode setting enabled by default\noptions i915 enable_fbc=1\n", 0o644),
    )
    return GraphicsConfigurationPlan(root, files, tuple(packages))


class IntelGraphicsConfigurator:
    def execute(self, plan: GraphicsConfigurationPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for relative, content, mode in plan.files:
            target = plan.rootfs / str(relative).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise IntelGraphicsError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temporary = target.with_name(target.name + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(mode)
            temporary.replace(target)
            written.append(target)
        return tuple(written)


def write_graphics_report(report: GraphicsReport, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise IntelGraphicsError(f"No s'escriurà sobre un enllaç simbòlic: {destination}")
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
