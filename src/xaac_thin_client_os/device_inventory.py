"""Deterministic device inventory for XAAC Agent and XMS (phase 6.7)."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

import yaml


class DeviceInventoryError(RuntimeError):
    """Raised when inventory configuration or collection is unsafe."""


_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise DeviceInventoryError(f"Ruta d'inventari insegura: {field}")
    return path


def load_device_inventory_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DeviceInventoryError(f"No s'ha pogut carregar el perfil d'inventari: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "inventory", "xaac_packages", "paths"} or raw.get("schema_version") != 1:
        raise DeviceInventoryError("Esquema d'inventari invàlid")
    inventory = raw["inventory"]
    if not isinstance(inventory, dict) or set(inventory) != {"format", "version", "include_packages", "include_peripherals", "maximum_packages"}:
        raise DeviceInventoryError("Configuració d'inventari incompleta")
    if inventory["format"] != "xaac-device-inventory" or inventory["version"] != 1:
        raise DeviceInventoryError("Format o versió d'inventari no compatible")
    if inventory["include_packages"] is not True or inventory["include_peripherals"] is not True:
        raise DeviceInventoryError("L'inventari complet és obligatori")
    if not isinstance(inventory["maximum_packages"], int) or not 1 <= inventory["maximum_packages"] <= 10000:
        raise DeviceInventoryError("Límit de paquets invàlid")
    packages = raw["xaac_packages"]
    if not isinstance(packages, list) or len(packages) != len(set(packages)) or not all(isinstance(v, str) and _PACKAGE.fullmatch(v) for v in packages):
        raise DeviceInventoryError("Llista de paquets XAAC invàlida")
    paths = raw["paths"]
    if not isinstance(paths, dict) or set(paths) != {"output", "state", "manifest"}:
        raise DeviceInventoryError("Rutes d'inventari incompletes")
    for key, value in paths.items():
        _absolute(value, f"paths.{key}")
    return raw


def inventory_digest(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "sha256"}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DeviceInventoryCollector:
    """Collect inventory from an installed rootfs without executing arbitrary code."""

    def __init__(self, rootfs: Path, profile_path: Path, *, now: Callable[[], datetime] | None = None):
        self.root = rootfs.resolve()
        if self.root == Path("/") or self.root.parent == Path("/"):
            raise DeviceInventoryError(f"Rootfs insegur: {self.root}")
        self.profile = load_device_inventory_profile(profile_path)
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _path(self, name: str) -> Path:
        return self.root / _absolute(self.profile["paths"][name], name).relative_to("/")

    @staticmethod
    def _read(path: Path, default: str = "unknown") -> str:
        try:
            value = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return default
        return value or default

    def _packages(self) -> list[dict[str, str]]:
        status = self.root / "var/lib/dpkg/status"
        if not status.is_file():
            return []
        result: list[dict[str, str]] = []
        for block in status.read_text(encoding="utf-8", errors="replace").split("\n\n"):
            fields: dict[str, str] = {}
            for line in block.splitlines():
                if ": " in line:
                    key, value = line.split(": ", 1)
                    fields[key] = value
            if fields.get("Status") == "install ok installed" and "Package" in fields and "Version" in fields:
                result.append({"name": fields["Package"], "version": fields["Version"], "architecture": fields.get("Architecture", "unknown")})
        result.sort(key=lambda item: item["name"])
        maximum = self.profile["inventory"]["maximum_packages"]
        return result[:maximum]

    def _peripherals(self) -> list[dict[str, str]]:
        devices = self.root / "sys/bus/usb/devices"
        result: list[dict[str, str]] = []
        if not devices.is_dir():
            return result
        for entry in sorted(devices.iterdir(), key=lambda p: p.name):
            vendor = self._read(entry / "idVendor", "")
            product = self._read(entry / "idProduct", "")
            if vendor and product:
                result.append({"bus_id": entry.name, "vendor_id": vendor.lower(), "product_id": product.lower(), "product": self._read(entry / "product")})
        return result

    def collect(self) -> dict[str, Any]:
        packages = self._packages()
        versions = {name: None for name in self.profile["xaac_packages"]}
        for item in packages:
            if item["name"] in versions:
                versions[item["name"]] = item["version"]
        document: dict[str, Any] = {
            "schema_version": 1,
            "format": "xaac-device-inventory",
            "generated_at": self.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "hardware": {
                "product_name": self._read(self.root / "sys/class/dmi/id/product_name"),
                "serial": self._read(self.root / "sys/class/dmi/id/product_serial"),
                "cpu_architecture": platform.machine() or "unknown",
            },
            "system": {
                "hostname": self._read(self.root / "etc/hostname"),
                "machine_id": self._read(self.root / "etc/machine-id"),
                "os_release": self._read(self.root / "etc/os-release"),
            },
            "packages": packages,
            "peripherals": self._peripherals(),
            "xaac_versions": versions,
            "status": {
                "agent_configured": (self.root / "etc/xaac/agent/agent.yaml").is_file(),
                "identity_present": (self.root / "var/lib/xaac-agent/identity/device.json").is_file(),
                "policy_present": (self.root / "var/lib/xaac-agent/policies/active/policy.json").is_file(),
            },
        }
        document["sha256"] = inventory_digest(document)
        return document

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any], mode: int = 0o640) -> None:
        if path.is_symlink():
            raise DeviceInventoryError(f"No s'utilitzarà un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, path)

    def install(self, *, dry_run: bool = False) -> tuple[Path, ...]:
        output, state, manifest = (self._path(name) for name in ("output", "state", "manifest"))
        paths = (output, state, manifest)
        for path in paths:
            if path.is_symlink():
                raise DeviceInventoryError(f"No s'utilitzarà un enllaç simbòlic: {path}")
        if dry_run:
            return paths
        inventory = self.collect()
        self._atomic_json(output, inventory)
        self._atomic_json(state, {"schema_version": 1, "status": "collected", "generated_at": inventory["generated_at"], "sha256": inventory["sha256"]})
        self._atomic_json(manifest, {"schema_version": 1, "format": "xaac-device-inventory", "version": 1, "sections": ["hardware", "system", "packages", "peripherals", "xaac_versions", "status"]})
        return paths
