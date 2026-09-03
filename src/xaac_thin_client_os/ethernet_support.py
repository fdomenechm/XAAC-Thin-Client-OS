"""Ethernet detection, validation and rootfs configuration for Dell Wyse 3040."""
from __future__ import annotations

import fnmatch
import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class EthernetSupportError(RuntimeError):
    """Raised when Ethernet inspection or configuration is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class EthernetInterface:
    name: str
    mac_address: str | None
    driver: str | None
    carrier: bool
    operstate: str
    speed_mbps: int | None
    duplex: str | None
    wake_on_lan_modes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "mac_address": self.mac_address, "driver": self.driver,
            "carrier": self.carrier, "operstate": self.operstate, "speed_mbps": self.speed_mbps,
            "duplex": self.duplex, "wake_on_lan_modes": list(self.wake_on_lan_modes),
        }


@dataclass(frozen=True, slots=True)
class EthernetCheck:
    name: str
    status: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "expected": self.expected, "actual": self.actual}


@dataclass(frozen=True, slots=True)
class EthernetReport:
    profile: str
    compatible: bool
    selected_interface: EthernetInterface | None
    interfaces: tuple[EthernetInterface, ...]
    checks: tuple[EthernetCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile, "compatible": self.compatible,
            "selected_interface": self.selected_interface.to_dict() if self.selected_interface else None,
            "interfaces": [item.to_dict() for item in self.interfaces],
            "checks": [item.to_dict() for item in self.checks],
        }


class EthernetDetector:
    def __init__(self, *, root: Path = Path("/")) -> None:
        self.root = root

    def _read(self, relative: str) -> str | None:
        try:
            value = (self.root / relative.lstrip("/")).read_text(encoding="utf-8", errors="replace").strip()
        except (OSError, UnicodeError):
            return None
        return value or None

    def detect(self) -> tuple[EthernetInterface, ...]:
        net_root = self.root / "sys/class/net"
        if not net_root.is_dir():
            return ()
        result: list[EthernetInterface] = []
        for entry in sorted(net_root.iterdir(), key=lambda item: item.name):
            if entry.name == "lo":
                continue
            iface_type = self._read(f"sys/class/net/{entry.name}/type")
            if iface_type not in (None, "1"):
                continue
            driver: str | None = None
            driver_link = entry / "device/driver"
            try:
                if driver_link.exists() or driver_link.is_symlink():
                    driver = driver_link.resolve().name
            except OSError:
                driver = None
            speed_text = self._read(f"sys/class/net/{entry.name}/speed")
            try:
                speed = int(speed_text) if speed_text and int(speed_text) > 0 else None
            except ValueError:
                speed = None
            carrier = self._read(f"sys/class/net/{entry.name}/carrier") == "1"
            wol_text = self._read(f"sys/class/net/{entry.name}/device/power/wakeup") or ""
            wol_modes = ("magic",) if wol_text in {"enabled", "disabled"} else ()
            result.append(EthernetInterface(
                entry.name,
                self._read(f"sys/class/net/{entry.name}/address"),
                driver,
                carrier,
                self._read(f"sys/class/net/{entry.name}/operstate") or "unknown",
                speed,
                self._read(f"sys/class/net/{entry.name}/duplex"),
                wol_modes,
            ))
        return tuple(result)


def load_ethernet_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EthernetSupportError(f"No s'ha pogut carregar el perfil Ethernet: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("profile"), str):
        raise EthernetSupportError("Perfil Ethernet invàlid o esquema no suportat")
    required = ("interface", "driver", "addressing", "wake_on_lan", "recovery", "configuration")
    if not all(isinstance(raw.get(key), dict) for key in required):
        raise EthernetSupportError("El perfil Ethernet no conté totes les seccions obligatòries")
    return raw


def compare_ethernet(interfaces: tuple[EthernetInterface, ...], profile: dict[str, Any]) -> EthernetReport:
    settings = profile["interface"]
    patterns = tuple(str(item) for item in settings.get("name_patterns", []))
    candidates = tuple(item for item in interfaces if any(fnmatch.fnmatch(item.name, pattern) for pattern in patterns))
    selected = sorted(candidates, key=lambda item: (not item.carrier, -(item.speed_mbps or 0), item.name))[0] if candidates else None
    checks: list[EthernetCheck] = []

    def add(name: str, ok: bool, expected: object, actual: object, *, warning: bool = False) -> None:
        checks.append(EthernetCheck(name, "pass" if ok else ("warning" if warning else "fail"), str(expected), str(actual)))

    required = bool(settings.get("required", True))
    add("interface", selected is not None, patterns, selected.name if selected else "absent", warning=not required)
    if selected is not None:
        expected_modules = tuple(str(item) for item in profile["driver"].get("expected_modules", []))
        allow_alternative = bool(profile["driver"].get("allow_alternative", False))
        driver_expected = selected.driver in expected_modules
        driver_alternative = allow_alternative and selected.driver is not None and not driver_expected
        if driver_expected:
            add("driver", True, expected_modules, selected.driver)
        elif driver_alternative:
            add("driver", False, expected_modules, selected.driver, warning=True)
        else:
            add("driver", False, expected_modules, selected.driver)
        minimum = int(settings.get("minimum_speed_mbps", 100))
        speed_known = selected.speed_mbps is not None
        if not speed_known:
            add("link-speed", False, f">={minimum} Mbps", "unknown", warning=True)
        else:
            add("link-speed", selected.speed_mbps >= minimum, f">={minimum} Mbps", selected.speed_mbps)
        add("mac-address", bool(selected.mac_address and re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", selected.mac_address.lower())), "valid unicast MAC", selected.mac_address)
        add("carrier", selected.carrier, "connected", selected.operstate, warning=True)
        wol = profile["wake_on_lan"]
        preferred = str(wol.get("preferred_mode", "magic"))
        enabled_if_supported = bool(wol.get("enabled_if_supported", False))
        add("wake-on-lan", preferred in selected.wake_on_lan_modes or not enabled_if_supported, preferred, selected.wake_on_lan_modes or "not detected", warning=True)
    compatible = not any(item.status == "fail" for item in checks)
    return EthernetReport(str(profile["profile"]), compatible, selected, interfaces, tuple(checks))


@dataclass(frozen=True, slots=True)
class EthernetConfigurationPlan:
    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]
    mode: str
    interface_match: str

    def to_manifest(self) -> dict[str, object]:
        return {"mode": self.mode, "interface_match": self.interface_match, "files": [str(item[0]) for item in self.files]}


def create_ethernet_configuration_plan(
    rootfs: Path,
    profile_path: Path,
    *,
    mode: str | None = None,
    address: str | None = None,
    gateway: str | None = None,
    dns: tuple[str, ...] = (),
) -> EthernetConfigurationPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise EthernetSupportError(f"Rootfs insegur: {root}")
    profile = load_ethernet_profile(profile_path)
    selected_mode = mode or str(profile["addressing"].get("default_mode", "dhcp"))
    if selected_mode not in {"dhcp", "static"}:
        raise EthernetSupportError("Mode Ethernet invàlid")
    if selected_mode == "static" and not bool(profile["addressing"].get("allow_static", False)):
        raise EthernetSupportError("La configuració estàtica no està autoritzada")
    patterns = profile["interface"].get("name_patterns", [])
    if not isinstance(patterns, list) or not patterns or not all(isinstance(item, str) and item for item in patterns):
        raise EthernetSupportError("Patrons d'interfície invàlids")
    match = " ".join(patterns)
    network_lines = ["# XAAC Ethernet", "[Match]", f"Name={match}", "", "[Network]"]
    if selected_mode == "dhcp":
        network_lines += ["DHCP=ipv4", f"IPv6AcceptRA={'yes' if profile['addressing'].get('ipv6_accept_ra') else 'no'}"]
    else:
        if not address:
            raise EthernetSupportError("La IP amb prefix és obligatòria en mode estàtic")
        try:
            interface = ipaddress.ip_interface(address)
        except ValueError as exc:
            raise EthernetSupportError(f"Adreça estàtica invàlida: {address}") from exc
        if interface.version != 4:
            raise EthernetSupportError("Només IPv4 estàtica està suportada en aquesta fase")
        network_lines.append(f"Address={interface}")
        if gateway:
            try:
                gateway_ip = ipaddress.ip_address(gateway)
            except ValueError as exc:
                raise EthernetSupportError(f"Passarel·la invàlida: {gateway}") from exc
            if gateway_ip.version != 4:
                raise EthernetSupportError("La passarel·la ha de ser IPv4")
            network_lines.append(f"Gateway={gateway_ip}")
        for value in dns:
            try:
                network_lines.append(f"DNS={ipaddress.ip_address(value)}")
            except ValueError as exc:
                raise EthernetSupportError(f"DNS invàlid: {value}") from exc
    network_lines += ["", "[Link]", f"RequiredForOnline={'yes' if profile['recovery'].get('required_for_online') else 'no'}"]
    link_lines = ["# XAAC stable Ethernet naming", "[Match]", "Type=ether", "", "[Link]", "NamePolicy=keep kernel database onboard slot path", "MACAddressPolicy=persistent"]
    files = (
        (PurePosixPath(str(profile["configuration"]["network_file"])), "\n".join(network_lines) + "\n", 0o644),
        (PurePosixPath(str(profile["configuration"]["link_file"])), "\n".join(link_lines) + "\n", 0o644),
    )
    return EthernetConfigurationPlan(root, files, selected_mode, match)


class EthernetConfigurator:
    def execute(self, plan: EthernetConfigurationPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for relative, content, mode in plan.files:
            target = plan.rootfs / str(relative).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise EthernetSupportError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temporary = target.with_name(target.name + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(mode)
            temporary.replace(target)
            written.append(target)
        wants = plan.rootfs / "etc/systemd/system/multi-user.target.wants"
        wants.mkdir(parents=True, exist_ok=True)
        service = wants / "systemd-networkd.service"
        if service.is_symlink() or service.exists():
            service.unlink()
        service.symlink_to("/usr/lib/systemd/system/systemd-networkd.service")
        return tuple(written)


def write_ethernet_report(report: EthernetReport, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise EthernetSupportError(f"No s'escriurà sobre un enllaç simbòlic: {destination}")
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
