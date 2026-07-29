"""Transactional central RustDesk configuration for phase 8.3."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import yaml


class RustDeskConfigurationError(RuntimeError):
    """Raised when a managed RustDesk configuration is invalid or unsafe."""


_ENDPOINT = re.compile(r"^[A-Za-z0-9.-]+:[0-9]{1,5}$")
_KEY = re.compile(r"^[A-Za-z0-9_+=./:-]{16,256}$")


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise RustDeskConfigurationError(f"Ruta insegura: {field}")
    return path


def _endpoint(value: object, field: str) -> str:
    text = str(value)
    if not _ENDPOINT.fullmatch(text):
        raise RustDeskConfigurationError(f"Endpoint RustDesk invàlid: {field}")
    port = int(text.rsplit(":", 1)[1])
    if not 1 <= port <= 65535:
        raise RustDeskConfigurationError(f"Port RustDesk invàlid: {field}")
    return text


def load_rustdesk_configuration(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RustDeskConfigurationError(f"No s'ha pogut carregar la configuració RustDesk: {exc}") from exc
    expected = {"schema_version", "revision", "servers", "security", "proxy", "policies", "update", "outputs"}
    if not isinstance(raw, dict) or set(raw) != expected or raw["schema_version"] != 1:
        raise RustDeskConfigurationError("Esquema de configuració RustDesk invàlid")
    if not isinstance(raw["revision"], int) or raw["revision"] < 1:
        raise RustDeskConfigurationError("Revisió RustDesk invàlida")
    servers = raw["servers"]
    if not isinstance(servers, dict) or set(servers) != {"id", "relay", "api"}:
        raise RustDeskConfigurationError("Servidors RustDesk incomplets")
    _endpoint(servers["id"], "id")
    _endpoint(servers["relay"], "relay")
    api = urlparse(str(servers["api"]))
    if api.scheme != "https" or not api.hostname or api.username or api.password:
        raise RustDeskConfigurationError("API RustDesk insegura")
    security = raw["security"]
    if not isinstance(security, dict) or set(security) != {"public_key", "require_encryption", "allow_direct_ip"}:
        raise RustDeskConfigurationError("Seguretat RustDesk incompleta")
    if not _KEY.fullmatch(str(security["public_key"])) or security["require_encryption"] is not True or security["allow_direct_ip"] is not False:
        raise RustDeskConfigurationError("Política de seguretat RustDesk insegura")
    proxy = raw["proxy"]
    if not isinstance(proxy, dict) or set(proxy) != {"mode", "url", "no_proxy"} or proxy["mode"] not in {"system", "disabled", "manual"}:
        raise RustDeskConfigurationError("Proxy RustDesk invàlid")
    if proxy["mode"] == "manual":
        parsed = urlparse(str(proxy["url"]))
        if parsed.scheme not in {"http", "https", "socks5"} or not parsed.hostname:
            raise RustDeskConfigurationError("URL de proxy RustDesk invàlida")
    elif proxy["url"] is not None:
        raise RustDeskConfigurationError("URL de proxy inesperada")
    if not isinstance(proxy["no_proxy"], list) or not all(isinstance(item, str) and item for item in proxy["no_proxy"]):
        raise RustDeskConfigurationError("Excepcions de proxy RustDesk invàlides")
    policies = raw["policies"]
    policy_keys = {"managed", "allow_remote_configuration", "allow_unattended_access", "allow_file_transfer", "allow_tcp_tunneling"}
    if not isinstance(policies, dict) or set(policies) != policy_keys or not all(isinstance(v, bool) for v in policies.values()) or policies["managed"] is not True:
        raise RustDeskConfigurationError("Polítiques RustDesk invàlides")
    update = raw["update"]
    if not isinstance(update, dict) or set(update) != {"channel", "managed_by_xaac"} or update["channel"] not in {"stable", "pilot", "development"} or update["managed_by_xaac"] is not True:
        raise RustDeskConfigurationError("Actualització RustDesk invàlida")
    outputs = raw["outputs"]
    if not isinstance(outputs, dict) or set(outputs) != {"active", "staging", "backup"}:
        raise RustDeskConfigurationError("Eixides RustDesk incompletes")
    for key, value in outputs.items():
        _absolute(value, key)
    if len(set(outputs.values())) != 3:
        raise RustDeskConfigurationError("Les eixides RustDesk han de ser diferents")
    return raw


@dataclass(frozen=True, slots=True)
class RustDeskConfigurationPlan:
    rootfs: Path
    profile: dict[str, Any]

    def payload(self) -> dict[str, object]:
        return {key: self.profile[key] for key in ("schema_version", "revision", "servers", "security", "proxy", "policies", "update")}

    def target(self, name: str) -> Path:
        path = _absolute(self.profile["outputs"][name], name)
        return self.rootfs / path.relative_to("/")


def create_rustdesk_configuration_plan(rootfs: Path, profile_path: Path) -> RustDeskConfigurationPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise RustDeskConfigurationError(f"Rootfs insegur: {root}")
    return RustDeskConfigurationPlan(root, load_rustdesk_configuration(profile_path))


class RustDeskConfigurationManager:
    @staticmethod
    def _guard(path: Path) -> None:
        if path.is_symlink():
            raise RustDeskConfigurationError(f"No s'operarà sobre un enllaç simbòlic: {path}")

    @staticmethod
    def _write(path: Path, payload: dict[str, object]) -> None:
        RustDeskConfigurationManager._guard(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o640)
        temporary.replace(path)

    def apply(self, plan: RustDeskConfigurationPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        active, staging, backup = (plan.target(name) for name in ("active", "staging", "backup"))
        for path in (active, staging, backup):
            self._guard(path)
        self._write(staging, plan.payload())
        if active.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(active.read_bytes())
            backup.chmod(0o640)
        active.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(active)
        return tuple(path for path in (active, backup) if path.exists())

    def rollback(self, plan: RustDeskConfigurationPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        active, backup = plan.target("active"), plan.target("backup")
        self._guard(active); self._guard(backup)
        if not backup.is_file():
            raise RustDeskConfigurationError("No hi ha una configuració RustDesk anterior")
        self._write(active, json.loads(backup.read_text(encoding="utf-8")))
        return (active,)
