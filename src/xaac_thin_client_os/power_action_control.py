"""Controlled power actions for kiosk phase 5.7."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class PowerActionControlError(RuntimeError):
    """Raised when the power-action policy is invalid or unsafe."""


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise PowerActionControlError(f"Ruta insegura: {name}")
    return path


def load_power_action_control_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PowerActionControlError(f"No s'ha pogut carregar la política d'energia: {exc}") from exc
    required = {"schema_version", "policy", "actions", "agent", "protection", "recovery", "files"}
    if not isinstance(raw, dict) or set(raw) != required or raw.get("schema_version") != 1:
        raise PowerActionControlError("Esquema de control d'energia invàlid")
    policy = raw["policy"]
    if not isinstance(policy, dict) or set(policy) != {"identifier", "default_decision", "enforcement_mode", "kiosk_user"}:
        raise PowerActionControlError("Política d'energia incompleta")
    if policy["default_decision"] != "deny" or policy["enforcement_mode"] != "enforce" or policy["kiosk_user"] != "xaac-kiosk":
        raise PowerActionControlError("La política ha de denegar per defecte i aplicar-se a xaac-kiosk")
    actions = raw["actions"]
    if not isinstance(actions, dict) or set(actions) != {"poweroff", "reboot", "suspend", "hibernate"}:
        raise PowerActionControlError("Accions d'energia incompletes")
    for name, item in actions.items():
        if not isinstance(item, dict) or set(item) != {"kiosk_user", "confirmation_required"}:
            raise PowerActionControlError(f"Acció invàlida: {name}")
        if item["kiosk_user"] not in {"deny", "request-agent"} or not isinstance(item["confirmation_required"], bool):
            raise PowerActionControlError(f"Decisió invàlida: {name}")
    if actions["suspend"]["kiosk_user"] != "deny" or actions["hibernate"]["kiosk_user"] != "deny":
        raise PowerActionControlError("Suspensió i hibernació han d'estar bloquejades")
    agent = raw["agent"]
    if not isinstance(agent, dict) or set(agent) != {"service", "request_socket", "allowed_operations", "request_timeout_seconds", "fail_closed"}:
        raise PowerActionControlError("Configuració de l'Agent invàlida")
    if agent["allowed_operations"] != ["poweroff", "reboot"] or agent["fail_closed"] is not True:
        raise PowerActionControlError("L'Agent només pot autoritzar apagada i reinici en mode fail-closed")
    _safe_absolute(agent["request_socket"], "request_socket")
    protection = raw["protection"]
    expected_protection = {"inhibit_key_handling", "inhibit_lid_handling", "minimum_confirmation_seconds", "maximum_pending_seconds", "reject_duplicate_requests"}
    if not isinstance(protection, dict) or set(protection) != expected_protection:
        raise PowerActionControlError("Protecció contra accions accidentals invàlida")
    if protection["inhibit_key_handling"] is not True or protection["reject_duplicate_requests"] is not True:
        raise PowerActionControlError("Cal inhibir tecles i rebutjar peticions duplicades")
    if not 1 <= protection["minimum_confirmation_seconds"] <= protection["maximum_pending_seconds"]:
        raise PowerActionControlError("Intervals de confirmació invàlids")
    recovery = raw["recovery"]
    if not isinstance(recovery, dict) or set(recovery) != {"restart_session_after_client_failure", "reboot_after_supervisor_failure", "maximum_session_restarts", "restart_window_seconds"}:
        raise PowerActionControlError("Política de recuperació invàlida")
    if recovery["restart_session_after_client_failure"] is not True or recovery["reboot_after_supervisor_failure"] is not False:
        raise PowerActionControlError("La recuperació ha de prioritzar reiniciar la sessió, no el dispositiu")
    files = raw["files"]
    if not isinstance(files, dict) or set(files) != {"logind", "polkit", "request_helper", "policy"}:
        raise PowerActionControlError("Destinacions de fitxers invàlides")
    for key, value in files.items():
        _safe_absolute(value, key)
    return raw


@dataclass(frozen=True, slots=True)
class PowerActionControlPlan:
    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]

    def to_manifest(self) -> dict[str, object]:
        return {"files": [str(path) for path, _, _ in self.files], "default_decision": "deny", "agent_required": True}


def create_power_action_control_plan(rootfs: Path, profile_path: Path) -> PowerActionControlPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise PowerActionControlError(f"Rootfs insegur: {root}")
    profile = load_power_action_control_profile(profile_path)
    files = profile["files"]
    logind = """# Managed by XAAC Thin Client OS\n[Login]\nHandlePowerKey=ignore\nHandlePowerKeyLongPress=ignore\nHandleRebootKey=ignore\nHandleSuspendKey=ignore\nHandleHibernateKey=ignore\nHandleLidSwitch=ignore\n"""
    polkit = '''polkit.addRule(function(action, subject) {\n  if (subject.user == "xaac-kiosk" && (action.id.indexOf("org.freedesktop.login1.power-off") == 0 || action.id.indexOf("org.freedesktop.login1.reboot") == 0 || action.id.indexOf("org.freedesktop.login1.suspend") == 0 || action.id.indexOf("org.freedesktop.login1.hibernate") == 0)) {\n    return polkit.Result.NO;\n  }\n});\n'''
    socket = profile["agent"]["request_socket"]
    timeout = profile["agent"]["request_timeout_seconds"]
    helper = f'''#!/bin/sh\nset -eu\naction="${{1:-}}"\ncase "$action" in poweroff|reboot) ;; *) echo "Acció no autoritzada" >&2; exit 64;; esac\nexec /usr/bin/timeout {timeout} /usr/bin/socat - UNIX-CONNECT:{socket} <<EOF\n{{"operation":"$action","source":"xaac-kiosk","confirmed":true}}\nEOF\n'''
    effective = {key: value for key, value in profile.items() if key != "files"}
    return PowerActionControlPlan(root, (
        (_safe_absolute(files["logind"], "logind"), logind, 0o644),
        (_safe_absolute(files["polkit"], "polkit"), polkit, 0o644),
        (_safe_absolute(files["request_helper"], "request_helper"), helper, 0o750),
        (_safe_absolute(files["policy"], "policy"), json.dumps(effective, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640),
    ))


class PowerActionControlConfigurator:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise PowerActionControlError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        temporary.replace(path)

    def execute(self, plan: PowerActionControlPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written = []
        for relative, content, mode in plan.files:
            destination = plan.rootfs / relative.relative_to("/")
            self._write(destination, content, mode)
            written.append(destination)
        return tuple(written)
