"""On-demand RustDesk activation for phase 8.5."""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class RustDeskActivationError(RuntimeError):
    """Raised when an activation policy or request is invalid."""


def _path(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise RustDeskActivationError(f"Ruta insegura: {field}")
    return path


def load_rustdesk_activation_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RustDeskActivationError(f"No s'ha pogut carregar l'activació RustDesk: {exc}") from exc
    expected = {"schema_version", "activation", "token", "outputs"}
    if not isinstance(raw, dict) or set(raw) != expected or raw["schema_version"] != 1:
        raise RustDeskActivationError("Esquema d'activació RustDesk invàlid")
    activation = raw["activation"]
    required = {"service", "allowed_sources", "default_duration_minutes", "minimum_duration_minutes", "maximum_duration_minutes", "close_on_expiry"}
    if not isinstance(activation, dict) or set(activation) != required:
        raise RustDeskActivationError("Política d'activació RustDesk incompleta")
    if activation["service"] != "rustdesk-xaac.service":
        raise RustDeskActivationError("Servei RustDesk no autoritzat")
    sources = activation["allowed_sources"]
    if not isinstance(sources, list) or not sources or not set(sources) <= {"local", "xms"}:
        raise RustDeskActivationError("Orígens d'activació RustDesk invàlids")
    minimum = activation["minimum_duration_minutes"]
    default = activation["default_duration_minutes"]
    maximum = activation["maximum_duration_minutes"]
    if not all(isinstance(v, int) for v in (minimum, default, maximum)) or not (1 <= minimum <= default <= maximum <= 1440):
        raise RustDeskActivationError("Duracions d'activació RustDesk invàlides")
    if activation["close_on_expiry"] is not True:
        raise RustDeskActivationError("El tancament automàtic és obligatori")
    token = raw["token"]
    if not isinstance(token, dict) or set(token) != {"minimum_length", "hash_algorithm", "single_use"}:
        raise RustDeskActivationError("Política de token RustDesk incompleta")
    if not isinstance(token["minimum_length"], int) or token["minimum_length"] < 16 or token["hash_algorithm"] != "sha256" or token["single_use"] is not True:
        raise RustDeskActivationError("Política de token RustDesk invàlida")
    outputs = raw["outputs"]
    if not isinstance(outputs, dict) or set(outputs) != {"policy", "helper", "expiry_service", "expiry_timer", "state", "request"}:
        raise RustDeskActivationError("Eixides d'activació RustDesk incompletes")
    for key, value in outputs.items():
        _path(value, key)
    return raw


@dataclass(frozen=True, slots=True)
class RustDeskActivationPlan:
    rootfs: Path
    profile: dict[str, Any]

    def target(self, key: str) -> Path:
        path = _path(self.profile["outputs"][key], key)
        return self.rootfs / path.relative_to("/")


def create_rustdesk_activation_plan(rootfs: Path, profile_path: Path) -> RustDeskActivationPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise RustDeskActivationError(f"Rootfs insegur: {root}")
    return RustDeskActivationPlan(root, load_rustdesk_activation_profile(profile_path))


class RustDeskActivationManager:
    @staticmethod
    def _write(path: Path, text: str, mode: int) -> None:
        if path.is_symlink():
            raise RustDeskActivationError(f"No s'operarà sobre un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(mode)
        tmp.replace(path)

    def install(self, plan: RustDeskActivationPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        a = plan.profile["activation"]
        policy = {
            "schema_version": 1,
            "service": a["service"],
            "allowed_sources": a["allowed_sources"],
            "default_duration_minutes": a["default_duration_minutes"],
            "minimum_duration_minutes": a["minimum_duration_minutes"],
            "maximum_duration_minutes": a["maximum_duration_minutes"],
            "close_on_expiry": True,
        }
        helper = """#!/bin/sh
set -eu
case "${1:-}" in
  start) systemctl start rustdesk-xaac.service ;;
  stop) systemctl stop rustdesk-xaac.service; rm -f /run/xaac/rustdesk/activation-request.json ;;
  status) systemctl is-active rustdesk-xaac.service ;;
  *) echo "usage: xaac-rustdesk-access {start|stop|status}" >&2; exit 2 ;;
esac
"""
        expiry_service = """[Unit]
Description=Close expired XAAC Remote Support session

[Service]
Type=oneshot
ExecStart=/usr/libexec/xaac-rustdesk-access stop
"""
        expiry_timer = """[Unit]
Description=Expiry timer for XAAC Remote Support

[Timer]
AccuracySec=1s
Persistent=false
Unit=rustdesk-xaac-expiry.service

[Install]
WantedBy=timers.target
"""
        state = {"schema_version": 1, "active": False, "source": None, "expires_at": None, "token_fingerprint": None}
        paths = tuple(plan.target(k) for k in ("policy", "helper", "expiry_service", "expiry_timer", "state"))
        self._write(paths[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(paths[1], helper, 0o750)
        self._write(paths[2], expiry_service, 0o644)
        self._write(paths[3], expiry_timer, 0o644)
        self._write(paths[4], json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        return paths

    def activate(self, plan: RustDeskActivationPlan, *, source: str, duration_minutes: int | None = None, token: str | None = None, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
        a = plan.profile["activation"]
        t = plan.profile["token"]
        if source not in a["allowed_sources"]:
            raise RustDeskActivationError("Origen d'activació no autoritzat")
        duration = a["default_duration_minutes"] if duration_minutes is None else duration_minutes
        if not isinstance(duration, int) or not a["minimum_duration_minutes"] <= duration <= a["maximum_duration_minutes"]:
            raise RustDeskActivationError("Duració fora dels límits autoritzats")
        raw_token = token or secrets.token_urlsafe(24)
        if len(raw_token) < t["minimum_length"]:
            raise RustDeskActivationError("Token d'activació massa curt")
        issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expires = issued + timedelta(minutes=duration)
        fingerprint = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        request = {"schema_version": 1, "source": source, "issued_at": issued.isoformat(), "expires_at": expires.isoformat(), "duration_minutes": duration, "token_hash": fingerprint, "single_use": True}
        state = {"schema_version": 1, "active": True, "source": source, "expires_at": expires.isoformat(), "token_fingerprint": fingerprint[:12]}
        if not dry_run:
            self._write(plan.target("request"), json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o600)
            self._write(plan.target("state"), json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        return {**state, "token": raw_token, "duration_minutes": duration}

    def deactivate(self, plan: RustDeskActivationPlan, *, dry_run: bool = False) -> dict[str, Any]:
        state = {"schema_version": 1, "active": False, "source": None, "expires_at": None, "token_fingerprint": None}
        if not dry_run:
            request = plan.target("request")
            if request.is_symlink():
                raise RustDeskActivationError(f"No s'operarà sobre un enllaç simbòlic: {request}")
            request.unlink(missing_ok=True)
            self._write(plan.target("state"), json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        return state
