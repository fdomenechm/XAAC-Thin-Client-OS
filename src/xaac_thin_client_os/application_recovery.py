"""Application and kiosk-session recovery policy for phase 11.2."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class ApplicationRecoveryError(RuntimeError):
    """Raised when the application recovery policy is unsafe."""


_UNIT = re.compile(r"^[A-Za-z0-9@_.-]+\.service$")
_ALLOWED_DIAGNOSTICS = {
    "client-status", "session-status", "client-journal", "agent-status", "policy-metadata"
}
_ALLOWED_EVENTS = {
    "client_restart_failed", "session_restart_failed", "policy_rollback", "recovery_failed"
}


def _path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise ApplicationRecoveryError(f"Ruta insegura en {field}")
    return value


def _positive_int(value: object, field: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise ApplicationRecoveryError(f"Valor invàlid en {field}")
    return value


def load_application_recovery(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ApplicationRecoveryError(f"No s'ha pogut carregar la recuperació d'aplicació: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ApplicationRecoveryError("Política de recuperació d'aplicació invàlida")
    if raw.get("hardware_profile") != "wyse3040":
        raise ApplicationRecoveryError("Perfil de maquinari no suportat")
    if not isinstance(raw.get("recovery_id"), str) or not raw["recovery_id"].strip():
        raise ApplicationRecoveryError("recovery_id invàlid")

    client = raw.get("client")
    if not isinstance(client, dict):
        raise ApplicationRecoveryError("Configuració del client absent")
    for key in ("service", "session_service"):
        value = client.get(key)
        if not isinstance(value, str) or not _UNIT.fullmatch(value):
            raise ApplicationRecoveryError(f"Unitat systemd invàlida en client.{key}")
    _positive_int(client.get("restart_timeout_seconds"), "client.restart_timeout_seconds", 300)
    _positive_int(client.get("session_restart_timeout_seconds"), "client.session_restart_timeout_seconds", 600)
    _positive_int(client.get("max_client_restarts"), "client.max_client_restarts", 10)
    _positive_int(client.get("max_session_restarts"), "client.max_session_restarts", 10)

    cleanup = raw.get("state_cleanup")
    if not isinstance(cleanup, dict) or cleanup.get("enabled") is not True or cleanup.get("forbid_symlinks") is not True:
        raise ApplicationRecoveryError("Neteja d'estat insegura")
    preserve = cleanup.get("preserve")
    remove = cleanup.get("remove")
    if not isinstance(preserve, list) or not preserve or not isinstance(remove, list) or not remove:
        raise ApplicationRecoveryError("Rutes de neteja incompletes")
    cleanup["preserve"] = [_path(item, "state_cleanup.preserve") for item in preserve]
    cleanup["remove"] = [_path(item, "state_cleanup.remove") for item in remove]
    if set(cleanup["preserve"]) & set(cleanup["remove"]):
        raise ApplicationRecoveryError("Una ruta no pot preservar-se i eliminar-se alhora")

    rollback = raw.get("policy_rollback")
    if not isinstance(rollback, dict) or rollback.get("enabled") is not True:
        raise ApplicationRecoveryError("Rollback de política absent")
    for key in ("require_signature_validation", "require_schema_validation", "atomic_replace"):
        if rollback.get(key) is not True:
            raise ApplicationRecoveryError(f"Control obligatori desactivat: policy_rollback.{key}")
    rollback["current"] = _path(rollback.get("current"), "policy_rollback.current")
    rollback["previous"] = _path(rollback.get("previous"), "policy_rollback.previous")
    if rollback["current"] == rollback["previous"]:
        raise ApplicationRecoveryError("La política actual i l'anterior han de ser diferents")

    diagnostics = raw.get("diagnostics")
    if not isinstance(diagnostics, dict) or diagnostics.get("enabled") is not True:
        raise ApplicationRecoveryError("Diagnòstic obligatori absent")
    collect = diagnostics.get("collect")
    if not isinstance(collect, list) or set(collect) != _ALLOWED_DIAGNOSTICS or len(collect) != len(set(collect)):
        raise ApplicationRecoveryError("Conjunt de diagnòstics incomplet")
    _positive_int(diagnostics.get("journal_lines"), "diagnostics.journal_lines", 5000)
    diagnostics["output_directory"] = _path(diagnostics.get("output_directory"), "diagnostics.output_directory")
    if diagnostics.get("preserve_on_success") is not True:
        raise ApplicationRecoveryError("Els diagnòstics s'han de conservar")

    safety = raw.get("safety")
    if not isinstance(safety, dict) or safety.get("automatic_factory_reset") is not False:
        raise ApplicationRecoveryError("El factory reset automàtic està prohibit")
    for key in ("fail_closed", "preserve_evidence", "destructive_actions_require_confirmation"):
        if safety.get(key) is not True:
            raise ApplicationRecoveryError(f"Control de seguretat obligatori desactivat: {key}")

    notifications = raw.get("notifications")
    if not isinstance(notifications, dict) or set(notifications.get("destinations", [])) != {"agent", "xms"}:
        raise ApplicationRecoveryError("Cal notificar Agent i XMS")
    events = notifications.get("notify_on")
    if not isinstance(events, list) or set(events) != _ALLOWED_EVENTS or len(events) != len(set(events)):
        raise ApplicationRecoveryError("Esdeveniments de notificació incomplets")

    outputs = raw.get("outputs")
    required = {"policy", "state", "runner", "service"}
    if not isinstance(outputs, dict) or set(outputs) != required:
        raise ApplicationRecoveryError("outputs incomplet")
    raw["outputs"] = {key: _path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class ApplicationRecoveryPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "recovery_id": self.profile["recovery_id"],
            "hardware_profile": self.profile["hardware_profile"],
            "client_service": self.profile["client"]["service"],
            "session_service": self.profile["client"]["session_service"],
            "policy_rollback": True,
            "diagnostic_count": len(self.profile["diagnostics"]["collect"]),
        }


def create_application_recovery_plan(rootfs: Path, profile_path: Path) -> ApplicationRecoveryPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise ApplicationRecoveryError(f"Rootfs insegur: {root}")
    return ApplicationRecoveryPlan(root, load_application_recovery(profile_path))


class ApplicationRecoveryInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise ApplicationRecoveryError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def install(self, plan: ApplicationRecoveryPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in ("policy", "state", "runner", "service"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(),
            "status": "idle",
            "attempt": 0,
            "last_action": None,
            "last_reason": None,
            "last_started_at": None,
            "last_completed_at": None,
            "client_restarts": 0,
            "session_restarts": 0,
            "state_cleaned": False,
            "policy_rolled_back": False,
            "diagnostic_bundle": None,
            "last_error": None,
        }
        runner = """#!/bin/sh
set -eu
POLICY=/etc/xaac/recovery/application-recovery.json
STATE=/var/lib/xaac-recovery/application-recovery-state.json
[ -r \"$POLICY\" ] || { echo \"missing application recovery policy\" >&2; exit 2; }
[ -r \"$STATE\" ] || { echo \"missing application recovery state\" >&2; exit 2; }
exec /usr/bin/xaac-agent recovery application \"$@\"
"""
        service = """[Unit]
Description=XAAC application and kiosk session recovery
After=xaac-agent.service xaac-kiosk-session.service
ConditionPathExists=/etc/xaac/recovery/application-recovery.json

[Service]
Type=oneshot
ExecStart=/usr/libexec/xaac-application-recovery recover
User=root
Group=root
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/run/xaac-thin-client /var/cache/xaac-thin-client /var/lib/xaac-thin-client /var/lib/xaac-recovery /etc/xaac/policy
LockPersonality=yes
RestrictRealtime=yes
UMask=0027
"""
        self._write(targets[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[1], json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[2], runner, 0o750)
        self._write(targets[3], service, 0o644)
        return targets
