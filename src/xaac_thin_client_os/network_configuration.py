"""Deterministic minimal network configuration for the Debian rootfs."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import yaml

class NetworkConfigurationError(RuntimeError):
    """Raised when networking cannot be configured safely."""

@dataclass(frozen=True, slots=True)
class NetworkConfigurationPlan:
    rootfs: Path
    interface_match: str
    dhcp4: bool
    dhcp6: bool
    ipv6_accept_ra: bool
    required_for_online: bool
    use_resolved: bool
    fallback_dns: tuple[str, ...]

    def network_text(self) -> str:
        return "\n".join((
            "[Match]", f"Name={self.interface_match}", "", "[Network]",
            f"DHCP={'yes' if self.dhcp4 and self.dhcp6 else 'ipv4' if self.dhcp4 else 'ipv6' if self.dhcp6 else 'no'}",
            f"IPv6AcceptRA={'yes' if self.ipv6_accept_ra else 'no'}",
            f"RequiredForOnline={'yes' if self.required_for_online else 'no'}", "",
        ))

    def resolved_text(self) -> str:
        dns = " ".join(self.fallback_dns)
        return "\n".join(("[Resolve]", f"FallbackDNS={dns}", "DNSSEC=allow-downgrade", "DNSOverTLS=opportunistic", ""))

    def to_manifest(self) -> dict[str, object]:
        return {
            "rootfs": str(self.rootfs), "backend": "systemd-networkd",
            "interface_match": self.interface_match, "dhcp4": self.dhcp4,
            "dhcp6": self.dhcp6, "ipv6_accept_ra": self.ipv6_accept_ra,
            "required_for_online": self.required_for_online,
            "use_resolved": self.use_resolved, "fallback_dns": list(self.fallback_dns),
        }

@dataclass(frozen=True, slots=True)
class NetworkConfigurationResult:
    executed: bool
    log_path: Path
    files_written: tuple[Path, ...]

def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool): raise NetworkConfigurationError(f"{name} ha de ser booleà")
    return value

def create_network_configuration_plan(rootfs: Path, config_path: Path) -> NetworkConfigurationPlan:
    rootfs = rootfs.resolve()
    if rootfs == Path('/') or rootfs.name != 'rootfs' or rootfs.parent.parent.name != 'runs':
        raise NetworkConfigurationError('Ruta rootfs insegura')
    try: raw = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc: raise NetworkConfigurationError(f"No es pot llegir {config_path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get('schema_version') != 1: raise NetworkConfigurationError('config/network.yaml té un esquema no suportat')
    if set(raw) != {'schema_version','backend','interface_match','dhcp4','dhcp6','ipv6_accept_ra','required_for_online','dns'}:
        raise NetworkConfigurationError('Claus desconegudes o absents en network.yaml')
    if raw['backend'] != 'systemd-networkd': raise NetworkConfigurationError('Només systemd-networkd està suportat')
    match = raw['interface_match']
    if not isinstance(match, str) or not match or any(c.isspace() for c in match) or '/' in match: raise NetworkConfigurationError('interface_match no és vàlid')
    dns = raw['dns']
    if not isinstance(dns, dict) or set(dns) != {'use_resolved','fallback'} or not isinstance(dns['fallback'], list): raise NetworkConfigurationError('dns no és vàlid')
    fallback=[]
    import ipaddress
    for value in dns['fallback']:
        if not isinstance(value, str): raise NetworkConfigurationError('DNS fallback no vàlid')
        try: fallback.append(str(ipaddress.ip_address(value)))
        except ValueError as exc: raise NetworkConfigurationError(f'DNS fallback no vàlid: {value}') from exc
    dhcp4=_bool(raw['dhcp4'],'dhcp4'); dhcp6=_bool(raw['dhcp6'],'dhcp6')
    if not dhcp4 and not dhcp6: raise NetworkConfigurationError('Cal habilitar almenys DHCPv4 o DHCPv6')
    return NetworkConfigurationPlan(rootfs, match, dhcp4, dhcp6, _bool(raw['ipv6_accept_ra'],'ipv6_accept_ra'), _bool(raw['required_for_online'],'required_for_online'), _bool(dns['use_resolved'],'dns.use_resolved'), tuple(dict.fromkeys(fallback)))

class NetworkConfigurator:
    def __init__(self, *, geteuid: Callable[[], int] = os.geteuid) -> None: self._geteuid=geteuid
    @staticmethod
    def _write(path: Path, content: str) -> None:
        if path.is_symlink(): raise NetworkConfigurationError(f'No es pot sobreescriure un enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True, exist_ok=True); tmp=path.with_name(path.name+'.tmp'); tmp.write_text(content, encoding='utf-8'); tmp.chmod(0o644); tmp.replace(path)
    def execute(self, plan: NetworkConfigurationPlan, log_path: Path, *, dry_run: bool=False) -> NetworkConfigurationResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        files=(plan.rootfs/'etc/systemd/network/20-xaac-wired.network', plan.rootfs/'etc/systemd/resolved.conf.d/20-xaac.conf')
        with log_path.open('w', encoding='utf-8') as log:
            log.write(('DRY-RUN' if dry_run else 'EXECUTE')+' network configuration\n')
            for path in files: log.write(f'file={path}\n')
            if dry_run: return NetworkConfigurationResult(False, log_path, ())
            if self._geteuid()!=0: raise NetworkConfigurationError('La configuració real requereix privilegis de root')
            required=(plan.rootfs/'etc/debian_version', plan.rootfs/'usr/lib/systemd/system/systemd-networkd.service', plan.rootfs/'usr/lib/systemd/system/systemd-resolved.service')
            missing=[str(p) for p in required if not p.exists()]
            if missing: raise NetworkConfigurationError('Al rootfs falten requisits: '+', '.join(missing))
            self._write(files[0], plan.network_text())
            written=[files[0]]
            if plan.use_resolved:
                self._write(files[1], plan.resolved_text()); written.append(files[1])
                resolv=plan.rootfs/'etc/resolv.conf'
                if resolv.exists() or resolv.is_symlink(): resolv.unlink()
                resolv.symlink_to('/run/systemd/resolve/stub-resolv.conf')
            wants=plan.rootfs/'etc/systemd/system/multi-user.target.wants'; wants.mkdir(parents=True, exist_ok=True)
            for service in ('systemd-networkd.service','systemd-resolved.service'):
                if service.startswith('systemd-resolved') and not plan.use_resolved: continue
                link=wants/service
                if link.exists() or link.is_symlink(): link.unlink()
                link.symlink_to('/usr/lib/systemd/system/'+service)
        return NetworkConfigurationResult(True, log_path, tuple(written))
