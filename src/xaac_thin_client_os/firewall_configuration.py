"""Persistent nftables firewall configuration for XAAC Thin Client OS."""
from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml


class FirewallConfigurationError(RuntimeError):
    """Raised when the firewall cannot be configured safely."""


@dataclass(frozen=True, slots=True)
class FirewallConfigurationPlan:
    rootfs: Path
    enabled: bool
    input_policy: str
    forward_policy: str
    output_policy: str
    loopback: bool
    established: bool
    dhcp_client: bool
    icmp: bool
    management_sources_v4: tuple[str, ...]
    management_sources_v6: tuple[str, ...]
    ssh_port: int | None
    agent_tcp_ports: tuple[int, ...]
    agent_udp_ports: tuple[int, ...]
    rustdesk_tcp_ports: tuple[int, ...]
    rustdesk_udp_ports: tuple[int, ...]
    state_path: Path

    @staticmethod
    def _port_rule(protocol: str, ports: tuple[int, ...]) -> str:
        if len(ports) == 1:
            return f"{protocol} dport {ports[0]}"
        return f"{protocol} dport {{ {', '.join(map(str, ports))} }}"

    def ruleset_text(self) -> str:
        lines = ["#!/usr/sbin/nft -f", "# Managed by XAAC Thin Client OS", "flush ruleset", "table inet xaac_filter {"]
        if self.management_sources_v4:
            lines.append("  set management_sources_v4 { type ipv4_addr; flags interval; elements = { " + ", ".join(self.management_sources_v4) + " } }")
        if self.management_sources_v6:
            lines.append("  set management_sources_v6 { type ipv6_addr; flags interval; elements = { " + ", ".join(self.management_sources_v6) + " } }")
        lines.append(f"  chain input {{ type filter hook input priority 0; policy {self.input_policy};")
        if self.loopback:
            lines.append('    iifname "lo" accept')
        lines.append("    ct state invalid drop")
        if self.established:
            lines.append("    ct state established,related accept")
        if self.dhcp_client:
            lines.extend(("    udp sport 67 udp dport 68 accept", "    udp sport 547 udp dport 546 accept"))
        if self.icmp:
            lines.extend(("    ip protocol icmp icmp type { destination-unreachable, time-exceeded, parameter-problem, echo-request } accept", "    ip6 nexthdr ipv6-icmp icmpv6 type { destination-unreachable, packet-too-big, time-exceeded, parameter-problem, echo-request, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert } accept"))
        services: list[tuple[str, tuple[int, ...]]] = []
        if self.ssh_port is not None:
            services.append(("tcp", (self.ssh_port,)))
        services.extend((("tcp", self.agent_tcp_ports), ("udp", self.agent_udp_ports), ("tcp", self.rustdesk_tcp_ports), ("udp", self.rustdesk_udp_ports)))
        for family, source_set in (("ip", "management_sources_v4"), ("ip6", "management_sources_v6")):
            sources = self.management_sources_v4 if family == "ip" else self.management_sources_v6
            if not sources:
                continue
            for protocol, ports in services:
                if ports:
                    lines.append(f"    {family} saddr @{source_set} {self._port_rule(protocol, ports)} ct state new accept")
        lines.extend(("  }", f"  chain forward {{ type filter hook forward priority 0; policy {self.forward_policy}; }}", f"  chain output {{ type filter hook output priority 0; policy {self.output_policy}; }}", "}", ""))
        return "\n".join(lines)

    def to_manifest(self) -> dict[str, object]:
        return {
            "rootfs": str(self.rootfs), "enabled": self.enabled,
            "policy": {"input": self.input_policy, "forward": self.forward_policy, "output": self.output_policy},
            "management": {
                "sources_v4": list(self.management_sources_v4), "sources_v6": list(self.management_sources_v6),
                "ssh_port": self.ssh_port,
                "agent": {"tcp_ports": list(self.agent_tcp_ports), "udp_ports": list(self.agent_udp_ports)},
                "rustdesk": {"tcp_ports": list(self.rustdesk_tcp_ports), "udp_ports": list(self.rustdesk_udp_ports)},
            },
            "state_path": str(self.state_path),
        }


@dataclass(frozen=True, slots=True)
class FirewallConfigurationResult:
    executed: bool
    log_path: Path
    files_written: tuple[Path, ...]


def _load(path: Path) -> dict[str, object]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FirewallConfigurationError(f"No es pot llegir {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise FirewallConfigurationError(f"{path} ha de contindre un mapa YAML")
    return raw


def _ports(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise FirewallConfigurationError(f"{label} ha de ser una llista")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 65535:
            raise FirewallConfigurationError(f"Port no vàlid en {label}: {item}")
        if item not in result:
            result.append(item)
    return tuple(sorted(result))


def create_firewall_configuration_plan(rootfs: Path, config_path: Path, ssh_config_path: Path) -> FirewallConfigurationPlan:
    rootfs = rootfs.resolve()
    if rootfs == Path("/") or rootfs.parent == Path("/") or rootfs.name != "rootfs":
        raise FirewallConfigurationError("Ruta rootfs insegura")
    raw = _load(config_path)
    if raw.get("schema_version") != 2 or set(raw) != {"schema_version", "enabled", "policy", "allow", "management", "state"}:
        raise FirewallConfigurationError("config/firewall.yaml té un esquema no suportat")
    policy, allow, management, state = raw["policy"], raw["allow"], raw["management"], raw["state"]
    if not isinstance(policy, dict) or set(policy) != {"input", "forward", "output"}:
        raise FirewallConfigurationError("policy no és vàlid")
    if not isinstance(allow, dict) or set(allow) != {"loopback", "established", "dhcp_client", "icmp"}:
        raise FirewallConfigurationError("allow no és vàlid")
    if any(not isinstance(value, bool) for value in allow.values()):
        raise FirewallConfigurationError("Els valors allow han de ser booleans")
    if not isinstance(raw["enabled"], bool):
        raise FirewallConfigurationError("enabled ha de ser booleà")
    policies = {key: policy[key] for key in ("input", "forward", "output")}
    if any(value not in {"accept", "drop"} for value in policies.values()):
        raise FirewallConfigurationError("Les polítiques només poden ser accept o drop")
    if policies["input"] != "drop" or policies["forward"] != "drop":
        raise FirewallConfigurationError("Les polítiques input i forward han de ser drop")
    if not isinstance(management, dict) or set(management) != {"sources", "ssh_from_config", "agent", "rustdesk"}:
        raise FirewallConfigurationError("management no és vàlid")
    if not isinstance(management["sources"], list) or not isinstance(management["ssh_from_config"], bool):
        raise FirewallConfigurationError("Fonts de gestió no vàlides")
    v4: list[str] = []; v6: list[str] = []
    for source in management["sources"]:
        try:
            network = ipaddress.ip_network(source, strict=True)
        except (TypeError, ValueError) as exc:
            raise FirewallConfigurationError(f"Xarxa de gestió no vàlida: {source}") from exc
        (v4 if network.version == 4 else v6).append(str(network))
    if not (v4 or v6):
        raise FirewallConfigurationError("Cal almenys una xarxa de gestió")
    service_ports: dict[str, tuple[int, ...]] = {}
    for service in ("agent", "rustdesk"):
        value = management[service]
        if not isinstance(value, dict) or set(value) != {"enabled", "tcp_ports", "udp_ports"} or not isinstance(value["enabled"], bool):
            raise FirewallConfigurationError(f"Servei {service} no vàlid")
        service_ports[f"{service}_tcp"] = _ports(value["tcp_ports"], f"management.{service}.tcp_ports") if value["enabled"] else ()
        service_ports[f"{service}_udp"] = _ports(value["udp_ports"], f"management.{service}.udp_ports") if value["enabled"] else ()
    ssh_port: int | None = None
    if management["ssh_from_config"]:
        ssh = _load(ssh_config_path)
        try:
            ssh_port = int(ssh["port"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FirewallConfigurationError("config/ssh.yaml no és compatible") from exc
        if not 1 <= ssh_port <= 65535:
            raise FirewallConfigurationError("Port SSH no vàlid")
    if not isinstance(state, dict) or set(state) != {"path"} or not isinstance(state["path"], str) or not state["path"].startswith("/var/lib/xaac-agent/"):
        raise FirewallConfigurationError("Ruta d'estat no vàlida")
    return FirewallConfigurationPlan(rootfs, raw["enabled"], policies["input"], policies["forward"], policies["output"], allow["loopback"], allow["established"], allow["dhcp_client"], allow["icmp"], tuple(v4), tuple(v6), ssh_port, service_ports["agent_tcp"], service_ports["agent_udp"], service_ports["rustdesk_tcp"], service_ports["rustdesk_udp"], Path(state["path"]))


class FirewallConfigurator:
    def __init__(self, *, geteuid: Callable[[], int] = os.geteuid) -> None:
        self._geteuid = geteuid

    @staticmethod
    def _write(path: Path, content: str, mode: int = 0o600) -> None:
        if path.is_symlink():
            raise FirewallConfigurationError(f"No es pot sobreescriure un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        temporary.replace(path)

    def execute(self, plan: FirewallConfigurationPlan, log_path: Path, *, dry_run: bool = False) -> FirewallConfigurationResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        rules = plan.rootfs / "etc/nftables.conf"
        state = plan.rootfs / plan.state_path.relative_to("/")
        with log_path.open("w", encoding="utf-8") as log:
            log.write(("DRY-RUN" if dry_run else "EXECUTE") + " firewall configuration\n")
            log.write(plan.ruleset_text())
            if dry_run:
                return FirewallConfigurationResult(False, log_path, ())
            if self._geteuid() != 0:
                raise FirewallConfigurationError("La configuració real requereix privilegis de root")
            required = (plan.rootfs / "etc/debian_version", plan.rootfs / "usr/lib/systemd/system/nftables.service", plan.rootfs / "usr/sbin/nft")
            missing = [str(path) for path in required if not path.exists()]
            if missing:
                raise FirewallConfigurationError("Al rootfs falten requisits: " + ", ".join(missing))
            self._write(rules, plan.ruleset_text())
            self._write(state, json.dumps({"schema_version": 1, "backend": "nftables", **plan.to_manifest()}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", 0o640)
            wants = plan.rootfs / "etc/systemd/system/multi-user.target.wants"
            wants.mkdir(parents=True, exist_ok=True)
            link = wants / "nftables.service"
            if link.exists() or link.is_symlink():
                link.unlink()
            if plan.enabled:
                link.symlink_to("/usr/lib/systemd/system/nftables.service")
        return FirewallConfigurationResult(True, log_path, (rules, state))
