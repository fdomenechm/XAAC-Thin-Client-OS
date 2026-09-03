"""Transactional DHCP and static IPv4 configuration (phase 7.2)."""
from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class IpAddressingError(RuntimeError):
    """Raised when an addressing request is invalid or cannot be applied safely."""


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise IpAddressingError(f"Ruta insegura: {field}")
    return path


def load_ip_addressing_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise IpAddressingError(f"No s'ha pogut carregar el perfil IP: {exc}") from exc
    required = {"schema_version", "backend", "interface_match", "default_mode", "allowed_sources", "validation", "fallback", "rollback", "paths"}
    if not isinstance(raw, dict) or set(raw) != required or raw.get("schema_version") != 1:
        raise IpAddressingError("Esquema de configuració IP invàlid")
    if raw["backend"] != "systemd-networkd" or raw["default_mode"] != "dhcp":
        raise IpAddressingError("Backend o mode predeterminat no compatible")
    if raw["allowed_sources"] != ["local", "remote"]:
        raise IpAddressingError("Fonts de configuració no compatibles")
    if not isinstance(raw["interface_match"], str) or not raw["interface_match"] or "/" in raw["interface_match"]:
        raise IpAddressingError("Patró d'interfície invàlid")
    validation = raw["validation"]
    if not isinstance(validation, dict) or set(validation) != {"require_gateway_in_subnet", "maximum_dns_servers"}:
        raise IpAddressingError("Regles de validació incompletes")
    if validation["require_gateway_in_subnet"] is not True or not isinstance(validation["maximum_dns_servers"], int) or validation["maximum_dns_servers"] < 1:
        raise IpAddressingError("Regles de validació invàlides")
    if raw["fallback"] != {"enabled": True, "mode": "dhcp"}:
        raise IpAddressingError("El fallback segur ha de ser DHCP")
    rollback = raw["rollback"]
    if not isinstance(rollback, dict) or rollback.get("enabled") is not True or not isinstance(rollback.get("keep_snapshots"), int) or rollback["keep_snapshots"] < 1:
        raise IpAddressingError("Política de rollback invàlida")
    paths = raw["paths"]
    if not isinstance(paths, dict) or set(paths) != {"active_network", "state", "snapshots", "pending"}:
        raise IpAddressingError("Rutes de configuració IP incompletes")
    for key, value in paths.items():
        _absolute(value, f"paths.{key}")
    return raw


@dataclass(frozen=True, slots=True)
class IpAddressingRequest:
    source: str
    mode: str
    address: str | None = None
    gateway: str | None = None
    dns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IpAddressingPlan:
    rootfs: Path
    profile: dict[str, Any]
    request: IpAddressingRequest
    network_text: str

    def path(self, name: str) -> Path:
        return self.rootfs / _absolute(self.profile["paths"][name], name).relative_to("/")


def create_ip_addressing_plan(rootfs: Path, profile_path: Path, request: IpAddressingRequest) -> IpAddressingPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise IpAddressingError(f"Rootfs insegur: {root}")
    profile = load_ip_addressing_profile(profile_path)
    if request.source not in profile["allowed_sources"]:
        raise IpAddressingError("Font de configuració no autoritzada")
    if request.mode not in {"dhcp", "static"}:
        raise IpAddressingError("Mode d'adreçament invàlid")
    lines = ["# Managed by XAAC Thin Client OS", "[Match]", f"Name={profile['interface_match']}", "Type=ether", "", "[Network]"]
    if request.mode == "dhcp":
        if request.address or request.gateway or request.dns:
            raise IpAddressingError("DHCP no admet paràmetres estàtics")
        lines += ["DHCP=ipv4", "LinkLocalAddressing=ipv6", "IPv6AcceptRA=yes", "RequiredForOnline=yes"]
    else:
        if not request.address or not request.gateway:
            raise IpAddressingError("L'adreça i la passarel·la són obligatòries")
        try:
            interface = ipaddress.ip_interface(request.address)
            gateway = ipaddress.ip_address(request.gateway)
        except ValueError as exc:
            raise IpAddressingError(f"Configuració IPv4 invàlida: {exc}") from exc
        if interface.version != 4 or gateway.version != 4:
            raise IpAddressingError("Només IPv4 estàtica està suportada")
        if gateway not in interface.network:
            raise IpAddressingError("La passarel·la ha d'estar dins de la subxarxa")
        maximum = profile["validation"]["maximum_dns_servers"]
        if len(request.dns) > maximum:
            raise IpAddressingError("Massa servidors DNS")
        parsed_dns: list[str] = []
        for value in request.dns:
            try:
                server = ipaddress.ip_address(value)
            except ValueError as exc:
                raise IpAddressingError(f"Servidor DNS invàlid: {value}") from exc
            if server.version != 4:
                raise IpAddressingError("Només DNS IPv4 està suportat")
            parsed_dns.append(str(server))
        lines += [f"Address={interface}", f"Gateway={gateway}"]
        if parsed_dns:
            lines.append(f"DNS={' '.join(parsed_dns)}")
        lines += ["DHCP=no", "LinkLocalAddressing=ipv6", "IPv6AcceptRA=no", "RequiredForOnline=yes"]
    return IpAddressingPlan(root, profile, request, "\n".join(lines) + "\n")


class IpAddressingManager:
    @staticmethod
    def _write(path: Path, content: str, mode: int = 0o640) -> None:
        if path.is_symlink():
            raise IpAddressingError(f"No se sobreescriurà un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, path)

    def apply(self, plan: IpAddressingPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        active, state, snapshots, pending = (plan.path(name) for name in ("active_network", "state", "snapshots", "pending"))
        if dry_run:
            return active, state, pending
        for path in (active, state, pending):
            if path.is_symlink():
                raise IpAddressingError(f"No se sobreescriurà un enllaç simbòlic: {path}")
        snapshots.mkdir(parents=True, exist_ok=True)
        if snapshots.is_symlink():
            raise IpAddressingError(f"Directori de snapshots insegur: {snapshots}")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        if active.exists():
            self._write(snapshots / f"{timestamp}.network", active.read_text(encoding="utf-8"), 0o600)
        transaction = {"schema_version": 1, "source": plan.request.source, "mode": plan.request.mode, "status": "pending", "created_at": timestamp}
        self._write(pending, json.dumps(transaction, indent=2, sort_keys=True) + "\n", 0o600)
        self._write(active, plan.network_text, 0o644)
        state_data = {**transaction, "status": "applied", "address": plan.request.address, "gateway": plan.request.gateway, "dns": list(plan.request.dns), "fallback": "dhcp", "rollback_available": any(snapshots.glob("*.network"))}
        self._write(state, json.dumps(state_data, indent=2, sort_keys=True) + "\n")
        pending.unlink(missing_ok=True)
        keep = plan.profile["rollback"]["keep_snapshots"]
        for old in sorted(snapshots.glob("*.network"), reverse=True)[keep:]:
            old.unlink()
        return active, state

    def rollback(self, plan: IpAddressingPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        active, state, snapshots = plan.path("active_network"), plan.path("state"), plan.path("snapshots")
        candidates = sorted(snapshots.glob("*.network"), reverse=True) if snapshots.exists() else []
        if not candidates:
            raise IpAddressingError("No hi ha cap snapshot per restaurar")
        if dry_run:
            return active, candidates[0], state
        self._write(active, candidates[0].read_text(encoding="utf-8"), 0o644)
        payload = {"schema_version": 1, "status": "rolled-back", "snapshot": candidates[0].name, "fallback": "dhcp"}
        self._write(state, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return active, state
