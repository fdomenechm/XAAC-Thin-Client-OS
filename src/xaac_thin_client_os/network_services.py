"""DNS, NTP and proxy configuration for phase 7.3."""
from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import yaml


class NetworkServicesError(RuntimeError):
    """Raised when DNS, NTP or proxy configuration is unsafe."""


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise NetworkServicesError(f"Ruta insegura: {field}")
    return path


def load_network_services_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise NetworkServicesError(f"No s'ha pogut carregar el perfil: {exc}") from exc
    required = {"schema_version", "backend", "allowed_sources", "limits", "defaults", "paths"}
    if not isinstance(raw, dict) or set(raw) != required or raw.get("schema_version") != 1:
        raise NetworkServicesError("Esquema de serveis de xarxa invàlid")
    if raw["backend"] != {"dns": "systemd-resolved", "ntp": "systemd-timesyncd"}:
        raise NetworkServicesError("Backends DNS/NTP no compatibles")
    if raw["allowed_sources"] != ["local", "remote"]:
        raise NetworkServicesError("Fonts no compatibles")
    limits = raw["limits"]
    if not isinstance(limits, dict) or set(limits) != {"dns_servers", "search_domains", "ntp_servers", "proxy_exceptions"}:
        raise NetworkServicesError("Límits incomplets")
    if any(not isinstance(v, int) or v < 1 for v in limits.values()):
        raise NetworkServicesError("Límits invàlids")
    defaults = raw["defaults"]
    if not isinstance(defaults, dict) or set(defaults) != {"dnssec", "dns_over_tls", "fallback_ntp"}:
        raise NetworkServicesError("Valors predeterminats incomplets")
    if defaults["dnssec"] not in {"yes", "no", "allow-downgrade"} or defaults["dns_over_tls"] not in {"yes", "no", "opportunistic"}:
        raise NetworkServicesError("Política DNS invàlida")
    if not isinstance(defaults["fallback_ntp"], list) or not defaults["fallback_ntp"]:
        raise NetworkServicesError("Cal almenys un NTP de fallback")
    paths = raw["paths"]
    expected = {"resolved", "timesyncd", "proxy_environment", "apt_proxy", "state", "diagnostics", "snapshot"}
    if not isinstance(paths, dict) or set(paths) != expected:
        raise NetworkServicesError("Rutes incompletes")
    for key, value in paths.items():
        _absolute(value, f"paths.{key}")
    return raw


def _host(value: str, label: str) -> str:
    candidate = value.strip().rstrip(".")
    if not candidate or len(candidate) > 253 or " " in candidate:
        raise NetworkServicesError(f"{label} invàlid: {value}")
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        labels = candidate.split(".")
        if any(not part or len(part) > 63 or part.startswith("-") or part.endswith("-") or not part.replace("-", "").isalnum() for part in labels):
            raise NetworkServicesError(f"{label} invàlid: {value}")
        return candidate.lower()


def _proxy(value: str | None) -> str | None:
    if value in {None, ""}:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise NetworkServicesError("URL de proxy invàlida")
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class NetworkServicesRequest:
    source: str = "local"
    dns: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    ntp: tuple[str, ...] = ()
    proxy: str | None = None
    no_proxy: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NetworkServicesPlan:
    rootfs: Path
    profile: dict[str, Any]
    request: NetworkServicesRequest
    files: dict[str, str]

    def path(self, name: str) -> Path:
        return self.rootfs / _absolute(self.profile["paths"][name], name).relative_to("/")


def create_network_services_plan(rootfs: Path, profile_path: Path, request: NetworkServicesRequest) -> NetworkServicesPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise NetworkServicesError(f"Rootfs insegur: {root}")
    profile = load_network_services_profile(profile_path)
    if request.source not in profile["allowed_sources"]:
        raise NetworkServicesError("Font no autoritzada")
    limits = profile["limits"]
    if len(request.dns) > limits["dns_servers"] or len(request.domains) > limits["search_domains"] or len(request.ntp) > limits["ntp_servers"] or len(request.no_proxy) > limits["proxy_exceptions"]:
        raise NetworkServicesError("S'ha superat un límit de configuració")
    dns = tuple(_host(v, "Servidor DNS") for v in request.dns)
    domains = tuple(_host(v.lstrip("~"), "Domini") for v in request.domains)
    ntp = tuple(_host(v, "Servidor NTP") for v in request.ntp)
    exceptions = tuple(_host(v.lstrip("."), "Excepció de proxy") for v in request.no_proxy)
    proxy = _proxy(request.proxy)
    resolved = ["# Managed by XAAC Thin Client OS", "[Resolve]"]
    if dns:
        resolved.append(f"DNS={' '.join(dns)}")
    if domains:
        resolved.append(f"Domains={' '.join(domains)}")
    resolved += [f"DNSSEC={profile['defaults']['dnssec']}", f"DNSOverTLS={profile['defaults']['dns_over_tls']}"]
    timesyncd = ["# Managed by XAAC Thin Client OS", "[Time]"]
    if ntp:
        timesyncd.append(f"NTP={' '.join(ntp)}")
    timesyncd.append(f"FallbackNTP={' '.join(profile['defaults']['fallback_ntp'])}")
    env_lines = ["# Managed by XAAC Thin Client OS"]
    apt_lines = ["// Managed by XAAC Thin Client OS"]
    if proxy:
        no_proxy = ",".join(exceptions)
        env_lines += [f'HTTP_PROXY="{proxy}"', f'HTTPS_PROXY="{proxy}"', f'NO_PROXY="{no_proxy}"']
        apt_lines += [f'Acquire::http::Proxy "{proxy}";', f'Acquire::https::Proxy "{proxy}";']
        for item in exceptions:
            apt_lines.append(f'Acquire::http::Proxy::{item} "DIRECT";')
            apt_lines.append(f'Acquire::https::Proxy::{item} "DIRECT";')
    else:
        env_lines += ['HTTP_PROXY=""', 'HTTPS_PROXY=""', 'NO_PROXY=""']
    files = {
        "resolved": "\n".join(resolved) + "\n",
        "timesyncd": "\n".join(timesyncd) + "\n",
        "proxy_environment": "\n".join(env_lines) + "\n",
        "apt_proxy": "\n".join(apt_lines) + "\n",
    }
    return NetworkServicesPlan(root, profile, request, files)


class NetworkServicesManager:
    @staticmethod
    def _write(path: Path, content: str, mode: int = 0o640) -> None:
        if path.is_symlink():
            raise NetworkServicesError(f"No se sobreescriurà un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.chmod(mode)
        os.replace(tmp, path)

    def apply(self, plan: NetworkServicesPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.path(name) for name in plan.files)
        state, diagnostics, snapshot = plan.path("state"), plan.path("diagnostics"), plan.path("snapshot")
        if dry_run:
            return (*targets, state, diagnostics)
        previous = {name: plan.path(name).read_text(encoding="utf-8") for name in plan.files if plan.path(name).exists()}
        self._write(snapshot, json.dumps({"schema_version": 1, "files": previous}, indent=2, sort_keys=True) + "\n", 0o600)
        for name, content in plan.files.items():
            self._write(plan.path(name), content, 0o644)
        payload = {"schema_version": 1, "status": "applied", "source": plan.request.source, "dns": list(plan.request.dns), "domains": list(plan.request.domains), "ntp": list(plan.request.ntp), "proxy_enabled": bool(plan.request.proxy), "no_proxy": list(plan.request.no_proxy)}
        self._write(state, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        diagnostic = {"schema_version": 1, "backend": plan.profile["backend"], "checks": {"dns_configured": bool(plan.request.dns), "ntp_configured": bool(plan.request.ntp or plan.profile['defaults']['fallback_ntp']), "proxy_configured": bool(plan.request.proxy)}, "commands": ["resolvectl status", "timedatectl timesync-status", "systemctl show-environment"]}
        self._write(diagnostics, json.dumps(diagnostic, indent=2, sort_keys=True) + "\n")
        return (*targets, state, diagnostics, snapshot)

    def rollback(self, plan: NetworkServicesPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        snapshot, state = plan.path("snapshot"), plan.path("state")
        if not snapshot.exists():
            raise NetworkServicesError("No hi ha snapshot de serveis de xarxa")
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        files = data.get("files")
        if not isinstance(files, dict):
            raise NetworkServicesError("Snapshot invàlid")
        targets = tuple(plan.path(name) for name in files)
        if dry_run:
            return (*targets, state)
        for name, content in files.items():
            if name not in plan.files or not isinstance(content, str):
                raise NetworkServicesError("Snapshot invàlid")
            self._write(plan.path(name), content, 0o644)
        self._write(state, json.dumps({"schema_version": 1, "status": "rolled-back"}, indent=2, sort_keys=True) + "\n")
        return (*targets, state)
