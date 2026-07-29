"""Consent controls for XAAC Remote Support (phase 8.6)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class RustDeskConsentError(RuntimeError):
    """Raised when a consent policy or decision is invalid."""


def _safe_path(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise RustDeskConsentError(f"Ruta insegura: {field}")
    return path


def load_rustdesk_consent_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RustDeskConsentError(f"No s'ha pogut carregar el consentiment RustDesk: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "consent", "notification", "logging", "outputs"} or raw["schema_version"] != 1:
        raise RustDeskConsentError("Esquema de consentiment RustDesk invàlid")
    consent = raw["consent"]
    expected = {"default_mode", "allowed_modes", "unattended", "prompt_timeout_seconds", "allow_user_cancel"}
    if not isinstance(consent, dict) or set(consent) != expected:
        raise RustDeskConsentError("Política de consentiment RustDesk incompleta")
    modes = consent["allowed_modes"]
    if modes != ["required", "authorized-unattended"] or consent["default_mode"] != "required":
        raise RustDeskConsentError("Modes de consentiment RustDesk invàlids")
    unattended = consent["unattended"]
    if not isinstance(unattended, dict) or set(unattended) != {"allowed_sources", "require_managed_device", "require_policy_authorization"}:
        raise RustDeskConsentError("Política sense consentiment incompleta")
    if not unattended["allowed_sources"] or not set(unattended["allowed_sources"]) <= {"xms"} or unattended["require_managed_device"] is not True or unattended["require_policy_authorization"] is not True:
        raise RustDeskConsentError("Accés sense consentiment no segur")
    timeout = consent["prompt_timeout_seconds"]
    if not isinstance(timeout, int) or not 15 <= timeout <= 300 or consent["allow_user_cancel"] is not True:
        raise RustDeskConsentError("Paràmetres de consentiment invàlids")
    notification = raw["notification"]
    if not isinstance(notification, dict) or set(notification) != {"show_operator", "show_reason", "show_expiry", "channel"} or notification["channel"] != "kiosk-overlay" or not all(notification[k] is True for k in ("show_operator", "show_reason", "show_expiry")):
        raise RustDeskConsentError("Notificació de consentiment incompleta")
    logging = raw["logging"]
    if not isinstance(logging, dict) or set(logging) != {"record_requests", "record_decisions", "record_cancellations"} or not all(logging.values()):
        raise RustDeskConsentError("Registre de consentiment incomplet")
    outputs = raw["outputs"]
    if not isinstance(outputs, dict) or set(outputs) != {"policy", "notifier", "state", "request", "audit_log"}:
        raise RustDeskConsentError("Eixides de consentiment incompletes")
    for key, value in outputs.items():
        _safe_path(value, key)
    return raw


@dataclass(frozen=True, slots=True)
class RustDeskConsentPlan:
    rootfs: Path
    profile: dict[str, Any]

    def target(self, key: str) -> Path:
        path = _safe_path(self.profile["outputs"][key], key)
        return self.rootfs / path.relative_to("/")


def create_rustdesk_consent_plan(rootfs: Path, profile_path: Path) -> RustDeskConsentPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise RustDeskConsentError(f"Rootfs insegur: {root}")
    return RustDeskConsentPlan(root, load_rustdesk_consent_profile(profile_path))


class RustDeskConsentManager:
    @staticmethod
    def _write(path: Path, text: str, mode: int) -> None:
        if path.is_symlink():
            raise RustDeskConsentError(f"No s'operarà sobre un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(mode)
        tmp.replace(path)

    @staticmethod
    def _timestamp(now: datetime | None = None) -> str:
        return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()

    def _audit(self, plan: RustDeskConsentPlan, event: dict[str, Any]) -> None:
        path = plan.target("audit_log")
        if path.is_symlink():
            raise RustDeskConsentError(f"No s'operarà sobre un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        path.chmod(0o640)

    def install(self, plan: RustDeskConsentPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        profile = plan.profile
        policy = {"schema_version": 1, **profile["consent"], "notification": profile["notification"], "logging": profile["logging"]}
        notifier = """#!/bin/sh
set -eu
request=/run/xaac/rustdesk/consent-request.json
[ -r "$request" ] || exit 1
exec /usr/bin/logger -t xaac-rustdesk-consent -- "Remote support consent requested"
"""
        state = {"schema_version": 1, "status": "idle", "session_id": None, "decision": None, "updated_at": None}
        paths = tuple(plan.target(k) for k in ("policy", "notifier", "state"))
        self._write(paths[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(paths[1], notifier, 0o750)
        self._write(paths[2], json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        return paths

    def request(self, plan: RustDeskConsentPlan, *, session_id: str, source: str, operator: str, reason: str, expires_at: str, mode: str | None = None, managed_device: bool = False, policy_authorized: bool = False, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
        if not session_id.strip() or not operator.strip() or not reason.strip() or not expires_at.strip():
            raise RustDeskConsentError("La petició de consentiment és incompleta")
        selected = mode or plan.profile["consent"]["default_mode"]
        if selected not in plan.profile["consent"]["allowed_modes"]:
            raise RustDeskConsentError("Mode de consentiment no autoritzat")
        unattended = selected == "authorized-unattended"
        policy = plan.profile["consent"]["unattended"]
        if unattended and (source not in policy["allowed_sources"] or not managed_device or not policy_authorized):
            raise RustDeskConsentError("Accés sense consentiment no autoritzat")
        status = "approved" if unattended else "pending"
        decision = "policy-authorized" if unattended else None
        timestamp = self._timestamp(now)
        request = {"schema_version": 1, "session_id": session_id, "source": source, "operator": operator, "reason": reason, "expires_at": expires_at, "mode": selected, "status": status, "decision": decision, "created_at": timestamp}
        state = {"schema_version": 1, "status": status, "session_id": session_id, "decision": decision, "updated_at": timestamp}
        if not dry_run:
            self._write(plan.target("request"), json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o600)
            self._write(plan.target("state"), json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
            self._audit(plan, {"event": "consent-requested", **request})
        return state

    def decide(self, plan: RustDeskConsentPlan, *, decision: str, session_id: str, actor: str = "kiosk-user", now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
        if decision not in {"approve", "deny", "cancel"}:
            raise RustDeskConsentError("Decisió de consentiment invàlida")
        if not session_id.strip():
            raise RustDeskConsentError("Identificador de sessió absent")
        timestamp = self._timestamp(now)
        status = {"approve": "approved", "deny": "denied", "cancel": "cancelled"}[decision]
        state = {"schema_version": 1, "status": status, "session_id": session_id, "decision": decision, "updated_at": timestamp}
        if not dry_run:
            self._write(plan.target("state"), json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
            request = plan.target("request")
            if request.is_symlink():
                raise RustDeskConsentError(f"No s'operarà sobre un enllaç simbòlic: {request}")
            request.unlink(missing_ok=True)
            self._audit(plan, {"schema_version": 1, "event": "consent-decision", "session_id": session_id, "decision": decision, "status": status, "actor": actor, "timestamp": timestamp})
        return state
