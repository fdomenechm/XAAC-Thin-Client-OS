"""Definitive network manager configuration and Agent status integration (phase 7.1)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class NetworkManagerError(RuntimeError):
    """Raised when the network manager profile or installation is unsafe."""


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise NetworkManagerError(f"Ruta de xarxa insegura: {field}")
    return path


def load_network_manager_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise NetworkManagerError(f"No s'ha pogut carregar el perfil de xarxa: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "manager", "ethernet", "agent", "paths"}:
        raise NetworkManagerError("Esquema del gestor de xarxa invàlid")
    if raw.get("schema_version") != 1:
        raise NetworkManagerError("Versió del perfil de xarxa no compatible")
    manager = raw["manager"]
    if not isinstance(manager, dict) or set(manager) != {"backend", "renderer", "wait_online", "manage_ethernet", "exclusive"}:
        raise NetworkManagerError("Configuració del gestor incompleta")
    if manager["backend"] != "systemd-networkd" or manager["renderer"] != "networkd":
        raise NetworkManagerError("El backend definitiu ha de ser systemd-networkd")
    if any(manager[key] is not True for key in ("wait_online", "manage_ethernet", "exclusive")):
        raise NetworkManagerError("El gestor ha de controlar Ethernet de manera exclusiva i auditable")
    ethernet = raw["ethernet"]
    if not isinstance(ethernet, dict) or set(ethernet) != {"match", "dhcp", "required_for_online", "link_local"}:
        raise NetworkManagerError("Configuració Ethernet base incompleta")
    if not isinstance(ethernet["match"], str) or not ethernet["match"] or "/" in ethernet["match"]:
        raise NetworkManagerError("Patró Ethernet invàlid")
    if ethernet["dhcp"] not in {"ipv4", "yes"} or not isinstance(ethernet["required_for_online"], bool):
        raise NetworkManagerError("Paràmetres Ethernet invàlids")
    if ethernet["link_local"] not in {"no", "ipv6", "yes"}:
        raise NetworkManagerError("Link-local invàlid")
    agent = raw["agent"]
    if not isinstance(agent, dict) or set(agent) != {"integration", "status_format", "status_version", "notify_on_change"}:
        raise NetworkManagerError("Integració amb l'Agent incompleta")
    if agent != {"integration": "status-file", "status_format": "xaac-network-status", "status_version": 1, "notify_on_change": True}:
        raise NetworkManagerError("Integració amb l'Agent no compatible")
    paths = raw["paths"]
    required = {"network_file", "link_file", "manager_manifest", "agent_status", "agent_watch", "service_dropin"}
    if not isinstance(paths, dict) or set(paths) != required:
        raise NetworkManagerError("Rutes del gestor de xarxa incompletes")
    for key, value in paths.items():
        _absolute(value, f"paths.{key}")
    return raw


@dataclass(frozen=True, slots=True)
class NetworkManagerPlan:
    rootfs: Path
    profile: dict[str, Any]

    def path(self, name: str) -> Path:
        return self.rootfs / _absolute(self.profile["paths"][name], name).relative_to("/")

    def network_text(self) -> str:
        ethernet = self.profile["ethernet"]
        return "\n".join(("[Match]", f"Name={ethernet['match']}", "Type=ether", "", "[Network]", f"DHCP={ethernet['dhcp']}", f"LinkLocalAddressing={ethernet['link_local']}", f"RequiredForOnline={'yes' if ethernet['required_for_online'] else 'no'}", "IPv6AcceptRA=yes", ""))

    def link_text(self) -> str:
        return "\n".join(("[Match]", "OriginalName=en* eth*", "", "[Link]", "RequiredForOnline=yes", "ActivationPolicy=up", ""))


def create_network_manager_plan(rootfs: Path, profile_path: Path) -> NetworkManagerPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise NetworkManagerError(f"Rootfs insegur: {root}")
    return NetworkManagerPlan(root, load_network_manager_profile(profile_path))


class NetworkManagerConfigurator:
    @staticmethod
    def _write(path: Path, content: str, mode: int = 0o644) -> None:
        if path.is_symlink():
            raise NetworkManagerError(f"No se sobreescriurà un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, path)

    def install(self, plan: NetworkManagerPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        names = ("network_file", "link_file", "manager_manifest", "agent_status", "agent_watch", "service_dropin")
        paths = tuple(plan.path(name) for name in names)
        if dry_run:
            return paths
        for path in paths:
            if path.is_symlink():
                raise NetworkManagerError(f"No se sobreescriurà un enllaç simbòlic: {path}")
        self._write(paths[0], plan.network_text())
        self._write(paths[1], plan.link_text())
        manifest = {"schema_version": 1, "backend": "systemd-networkd", "exclusive": True, "ethernet_managed": True, "agent_integration": "status-file"}
        self._write(paths[2], json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        status = {"schema_version": 1, "format": "xaac-network-status", "version": 1, "state": "unknown", "backend": "systemd-networkd", "interface": None, "carrier": False, "addresses": [], "gateway": None, "dns": [], "updated_at": None}
        self._write(paths[3], json.dumps(status, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(paths[4], "\n".join(("# XAAC Agent network state source", f"XAAC_NETWORK_STATUS={plan.profile['paths']['agent_status']}", "XAAC_NETWORK_STATUS_FORMAT=xaac-network-status", "XAAC_NETWORK_STATUS_VERSION=1", "")))
        self._write(paths[5], "\n".join(("[Unit]", "After=systemd-networkd.service systemd-networkd-wait-online.service", "Wants=systemd-networkd.service", "", "[Service]", f"EnvironmentFile=-{plan.profile['paths']['agent_watch']}", "")))
        wants = plan.rootfs / "etc/systemd/system/multi-user.target.wants"
        wants.mkdir(parents=True, exist_ok=True)
        for service in ("systemd-networkd.service", "systemd-networkd-wait-online.service"):
            link = wants / service
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(f"/usr/lib/systemd/system/{service}")
        return paths
