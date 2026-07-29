"""Append-only audit trail for XAAC Remote Support sessions (phase 8.7)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class RustDeskSessionAuditError(RuntimeError):
    """Raised when the RustDesk session audit contract is violated."""


def _safe_path(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise RustDeskSessionAuditError(f"Ruta insegura: {field}")
    return path


def _parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RustDeskSessionAuditError(f"Data ISO 8601 invàlida: {field}") from exc
    if parsed.tzinfo is None:
        raise RustDeskSessionAuditError(f"La data ha d'incloure zona horària: {field}")
    return parsed.astimezone(timezone.utc)


def load_rustdesk_session_audit_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RustDeskSessionAuditError(f"No s'ha pogut carregar l'auditoria RustDesk: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "audit", "outputs"} or raw["schema_version"] != 1:
        raise RustDeskSessionAuditError("Esquema d'auditoria RustDesk invàlid")
    audit = raw["audit"]
    expected = {"required_fields", "allowed_end_statuses", "clock", "duration_unit", "append_only"}
    if not isinstance(audit, dict) or set(audit) != expected:
        raise RustDeskSessionAuditError("Política d'auditoria RustDesk incompleta")
    required = ["session_id", "operator", "device_id", "reason", "started_at"]
    if audit["required_fields"] != required:
        raise RustDeskSessionAuditError("Camps obligatoris d'auditoria invàlids")
    if audit["allowed_end_statuses"] != ["completed", "cancelled", "expired", "failed"]:
        raise RustDeskSessionAuditError("Estats finals d'auditoria invàlids")
    if audit["clock"] != "utc" or audit["duration_unit"] != "seconds" or audit["append_only"] is not True:
        raise RustDeskSessionAuditError("Paràmetres d'auditoria insegurs")
    outputs = raw["outputs"]
    if not isinstance(outputs, dict) or set(outputs) != {"journal", "active_session", "state"}:
        raise RustDeskSessionAuditError("Eixides d'auditoria incompletes")
    for key, value in outputs.items():
        _safe_path(value, key)
    return raw


@dataclass(frozen=True, slots=True)
class RustDeskSessionAuditPlan:
    rootfs: Path
    profile: dict[str, Any]

    def target(self, key: str) -> Path:
        path = _safe_path(self.profile["outputs"][key], key)
        return self.rootfs / path.relative_to("/")


def create_rustdesk_session_audit_plan(rootfs: Path, profile_path: Path) -> RustDeskSessionAuditPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise RustDeskSessionAuditError(f"Rootfs insegur: {root}")
    return RustDeskSessionAuditPlan(root, load_rustdesk_session_audit_profile(profile_path))


class RustDeskSessionAuditManager:
    @staticmethod
    def _timestamp(now: datetime | None = None) -> str:
        return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()

    @staticmethod
    def _write(path: Path, data: dict[str, Any], mode: int) -> None:
        if path.is_symlink():
            raise RustDeskSessionAuditError(f"No s'operarà sobre un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.chmod(mode)
        tmp.replace(path)

    @staticmethod
    def _append(path: Path, event: dict[str, Any]) -> None:
        if path.is_symlink():
            raise RustDeskSessionAuditError(f"No s'operarà sobre un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        path.chmod(0o640)

    def install(self, plan: RustDeskSessionAuditPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        state = {"schema_version": 1, "status": "idle", "session_id": None, "last_event": None, "updated_at": None}
        self._write(plan.target("state"), state, 0o640)
        return (plan.target("state"),)

    def start(self, plan: RustDeskSessionAuditPlan, *, session_id: str, operator: str, device_id: str, reason: str, started_at: str | None = None, source: str = "xms", now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
        if not all(value.strip() for value in (session_id, operator, device_id, reason)):
            raise RustDeskSessionAuditError("L'inici de sessió d'auditoria és incomplet")
        active = plan.target("active_session")
        if active.exists() or active.is_symlink():
            raise RustDeskSessionAuditError("Ja existeix una sessió RustDesk auditada activa")
        timestamp = started_at or self._timestamp(now)
        _parse_utc(timestamp, "started_at")
        record = {"schema_version": 1, "event": "session-started", "session_id": session_id, "operator": operator, "device_id": device_id, "reason": reason, "source": source, "started_at": timestamp}
        state = {"schema_version": 1, "status": "active", "session_id": session_id, "last_event": "session-started", "updated_at": timestamp}
        if not dry_run:
            self._write(active, record, 0o600)
            self._append(plan.target("journal"), record)
            self._write(plan.target("state"), state, 0o640)
        return state

    def end(self, plan: RustDeskSessionAuditPlan, *, session_id: str, status: str, ended_at: str | None = None, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
        if status not in plan.profile["audit"]["allowed_end_statuses"]:
            raise RustDeskSessionAuditError("Estat final de sessió RustDesk invàlid")
        active = plan.target("active_session")
        if active.is_symlink():
            raise RustDeskSessionAuditError(f"No s'operarà sobre un enllaç simbòlic: {active}")
        try:
            current = json.loads(active.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RustDeskSessionAuditError("No hi ha cap sessió RustDesk activa vàlida") from exc
        if current.get("session_id") != session_id:
            raise RustDeskSessionAuditError("La sessió activa no coincideix")
        end_text = ended_at or self._timestamp(now)
        start_dt = _parse_utc(str(current["started_at"]), "started_at")
        end_dt = _parse_utc(end_text, "ended_at")
        duration = int((end_dt - start_dt).total_seconds())
        if duration < 0:
            raise RustDeskSessionAuditError("La fi de sessió és anterior a l'inici")
        event = {**current, "event": "session-ended", "ended_at": end_text, "duration_seconds": duration, "status": status}
        state = {"schema_version": 1, "status": "idle", "session_id": None, "last_event": "session-ended", "last_session": session_id, "last_duration_seconds": duration, "updated_at": end_text}
        if not dry_run:
            self._append(plan.target("journal"), event)
            active.unlink()
            self._write(plan.target("state"), state, 0o640)
        return state
