"""Declarative recovery state model for XAAC Thin Client OS (phase 11.1)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class RecoveryModelError(RuntimeError):
    """Raised when the recovery model is unsafe or inconsistent."""


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryModelError(f"Valor invàlid en {field}")
    return value


def _absolute_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise RecoveryModelError(f"Ruta insegura en {field}")
    return value


def load_recovery_model(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RecoveryModelError(f"No s'ha pogut carregar el model: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise RecoveryModelError("Model de recuperació invàlid")
    if raw.get("hardware_profile") != "wyse3040":
        raise RecoveryModelError("Perfil de maquinari no suportat")
    _nonempty(raw.get("model_id"), "model_id")

    failures = raw.get("failure_classes")
    if not isinstance(failures, list) or not failures:
        raise RecoveryModelError("Cal definir classes de fallada")
    ids: list[str] = []
    counters: list[str] = []
    for index, item in enumerate(failures):
        if not isinstance(item, dict):
            raise RecoveryModelError("Classe de fallada invàlida")
        ids.append(_nonempty(item.get("id"), f"failure_classes[{index}].id"))
        counters.append(_nonempty(item.get("counter"), f"failure_classes[{index}].counter"))
        window = item.get("window_seconds")
        if not isinstance(window, int) or isinstance(window, bool) or window < 1:
            raise RecoveryModelError("Finestra temporal invàlida")
    if len(ids) != len(set(ids)) or len(counters) != len(set(counters)):
        raise RecoveryModelError("Classes o comptadors duplicats")

    thresholds = raw.get("thresholds")
    required_thresholds = ("degraded", "recovering", "safe", "manual_intervention")
    if not isinstance(thresholds, dict) or tuple(thresholds) != required_thresholds:
        raise RecoveryModelError("Llindars incomplets o desordenats")
    values = [thresholds[name] for name in required_thresholds]
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values):
        raise RecoveryModelError("Llindar invàlid")
    if values != sorted(set(values)):
        raise RecoveryModelError("Els llindars han de ser estrictament creixents")

    states = raw.get("states")
    required_states = ("healthy", "degraded", "recovering", "safe", "manual_intervention")
    if not isinstance(states, dict) or tuple(states) != required_states:
        raise RecoveryModelError("Model d'estats incomplet o desordenat")
    severities: list[int] = []
    for name, state in states.items():
        if not isinstance(state, dict):
            raise RecoveryModelError(f"Estat invàlid: {name}")
        severity = state.get("severity")
        actions = state.get("actions")
        notify = state.get("notify")
        if not isinstance(severity, int) or isinstance(severity, bool) or severity < 0:
            raise RecoveryModelError("Severitat invàlida")
        if not isinstance(actions, list) or not actions or not all(isinstance(action, str) and action for action in actions):
            raise RecoveryModelError("Accions de recuperació invàlides")
        if not isinstance(notify, list) or not set(notify) <= {"agent", "xms"}:
            raise RecoveryModelError("Destinataris de notificació invàlids")
        severities.append(severity)
    if severities != list(range(len(required_states))):
        raise RecoveryModelError("Les severitats han de ser consecutives")
    if "agent" not in states["safe"]["notify"] or "xms" not in states["safe"]["notify"]:
        raise RecoveryModelError("L'estat segur ha de notificar Agent i XMS")

    safety = raw.get("safety")
    if not isinstance(safety, dict):
        raise RecoveryModelError("Política de seguretat absent")
    if safety.get("automatic_factory_reset") is not False:
        raise RecoveryModelError("El factory reset automàtic està prohibit")
    for key in ("destructive_actions_require_confirmation", "preserve_evidence", "fail_closed"):
        if safety.get(key) is not True:
            raise RecoveryModelError(f"Control de seguretat obligatori desactivat: {key}")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"policy", "state"}:
        raise RecoveryModelError("outputs incomplet")
    raw["outputs"] = {key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


def classify_recovery_state(profile: dict[str, Any], counters: dict[str, int]) -> str:
    """Return the most severe state implied by any failure counter."""
    known = {item["counter"] for item in profile["failure_classes"]}
    if set(counters) - known:
        raise RecoveryModelError("Comptador de fallada desconegut")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counters.values()):
        raise RecoveryModelError("Valor de comptador invàlid")
    maximum = max(counters.values(), default=0)
    state = "healthy"
    for candidate in ("degraded", "recovering", "safe", "manual_intervention"):
        if maximum >= profile["thresholds"][candidate]:
            state = candidate
    return state


@dataclass(frozen=True, slots=True)
class RecoveryModelPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "model_id": self.profile["model_id"],
            "hardware_profile": self.profile["hardware_profile"],
            "failure_class_count": len(self.profile["failure_classes"]),
            "state_count": len(self.profile["states"]),
            "initial_state": "healthy",
        }


def create_recovery_model_plan(rootfs: Path, profile_path: Path) -> RecoveryModelPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise RecoveryModelError(f"Rootfs insegur: {root}")
    return RecoveryModelPlan(root, load_recovery_model(profile_path))


class RecoveryModelInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise RecoveryModelError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: RecoveryModelPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = (plan.output("policy"), plan.output("state"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        counters = {item["counter"]: 0 for item in plan.profile["failure_classes"]}
        state = {
            **plan.manifest(),
            "status": "healthy",
            "counters": counters,
            "last_failure": None,
            "last_transition": None,
            "automatic_recovery_locked": False,
        }
        self._write(targets[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o644)
        self._write(targets[1], json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        return targets
