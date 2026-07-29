"""Declarative update model for XAAC Thin Client OS (phase 10.1)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class UpdateModelError(RuntimeError):
    """Raised when the update model is unsafe or inconsistent."""


_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


def _absolute_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise UpdateModelError(f"Ruta insegura en {field}")
    return value


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UpdateModelError(f"Valor invàlid en {field}")
    return value


def load_update_model(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UpdateModelError(f"No s'ha pogut carregar el model: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise UpdateModelError("Model d'actualització invàlid")
    if raw.get("hardware_profile") != "wyse3040":
        raise UpdateModelError("Perfil de maquinari no suportat")

    components = raw.get("components")
    if not isinstance(components, list) or not components:
        raise UpdateModelError("Cal definir components actualitzables")
    component_ids: list[str] = []
    for index, item in enumerate(components):
        if not isinstance(item, dict):
            raise UpdateModelError("Component invàlid")
        for key in ("id", "package", "kind", "restart"):
            item[key] = _nonempty(item.get(key), f"components[{index}].{key}")
        if not isinstance(item.get("critical"), bool):
            raise UpdateModelError("El camp critical ha de ser booleà")
        component_ids.append(item["id"])
    if len(component_ids) != len(set(component_ids)):
        raise UpdateModelError("Identificadors de component duplicats")

    channels = raw.get("channels")
    if not isinstance(channels, list) or len(channels) < 2:
        raise UpdateModelError("Cal definir almenys dos canals")
    channel_ids: list[str] = []
    priorities: list[int] = []
    for item in channels:
        if not isinstance(item, dict):
            raise UpdateModelError("Canal invàlid")
        channel_id = _nonempty(item.get("id"), "channels.id")
        priority = item.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority < 0:
            raise UpdateModelError("Prioritat de canal invàlida")
        if not isinstance(item.get("automatic"), bool):
            raise UpdateModelError("El camp automatic ha de ser booleà")
        target = item.get("promotion_target")
        if target is not None and not isinstance(target, str):
            raise UpdateModelError("Destinació de promoció invàlida")
        channel_ids.append(channel_id)
        priorities.append(priority)
    if len(channel_ids) != len(set(channel_ids)) or len(priorities) != len(set(priorities)):
        raise UpdateModelError("Canals o prioritats duplicats")
    for item in channels:
        target = item.get("promotion_target")
        if target is not None and target not in channel_ids:
            raise UpdateModelError("Canal de promoció inexistent")
        if target == item["id"]:
            raise UpdateModelError("Un canal no pot promocionar-se a si mateix")

    windows = raw.get("maintenance_windows")
    if not isinstance(windows, dict) or windows.get("timezone") != "Europe/Madrid":
        raise UpdateModelError("Finestra de manteniment invàlida")
    default = windows.get("default")
    if not isinstance(default, dict):
        raise UpdateModelError("Finestra predeterminada absent")
    days = default.get("days")
    if not isinstance(days, list) or not days or len(days) != len(set(days)) or not set(days) <= _DAYS:
        raise UpdateModelError("Dies de manteniment invàlids")
    if not isinstance(default.get("start"), str) or not _TIME.fullmatch(default["start"]):
        raise UpdateModelError("Hora d'inici invàlida")
    duration = default.get("duration_minutes")
    if not isinstance(duration, int) or isinstance(duration, bool) or not 1 <= duration <= 1440:
        raise UpdateModelError("Duració de manteniment invàlida")
    if not isinstance(windows.get("emergency_updates_bypass_window"), bool):
        raise UpdateModelError("Política d'emergència invàlida")

    versions = raw.get("version_policy")
    if not isinstance(versions, dict) or versions.get("format") != "semver":
        raise UpdateModelError("Política de versions invàlida")
    minimum = versions.get("minimum_os_version")
    if not isinstance(minimum, str) or not _SEMVER.fullmatch(minimum):
        raise UpdateModelError("Versió mínima invàlida")
    prerelease = versions.get("allow_prerelease_in")
    blocked = versions.get("blocked_versions")
    if not isinstance(prerelease, list) or not set(prerelease) <= set(channel_ids):
        raise UpdateModelError("Canals prerelease invàlids")
    if not isinstance(blocked, list) or not all(isinstance(v, str) and _SEMVER.fullmatch(v) for v in blocked):
        raise UpdateModelError("Versions bloquejades invàlides")
    if minimum in blocked:
        raise UpdateModelError("La versió mínima no pot estar bloquejada")
    if versions.get("allow_downgrade") is not False:
        raise UpdateModelError("Els downgrades han d'estar bloquejats per defecte")

    dependencies = raw.get("dependency_policy")
    if not isinstance(dependencies, dict):
        raise UpdateModelError("Política de dependències absent")
    if dependencies.get("require_declared_dependencies") is not True or dependencies.get("reject_cycles") is not True:
        raise UpdateModelError("La validació de dependències no es pot relaxar")
    atomic_sets = dependencies.get("atomic_component_sets")
    if not isinstance(atomic_sets, list):
        raise UpdateModelError("Conjunts atòmics invàlids")
    for group in atomic_sets:
        if not isinstance(group, list) or len(group) < 2 or len(group) != len(set(group)) or not set(group) <= set(component_ids):
            raise UpdateModelError("Conjunt atòmic invàlid")

    states = raw.get("states")
    if not isinstance(states, dict):
        raise UpdateModelError("Model d'estats absent")
    initial, terminal, transitions = states.get("initial"), states.get("terminal"), states.get("transitions")
    if not isinstance(initial, str) or not isinstance(terminal, list) or not isinstance(transitions, dict):
        raise UpdateModelError("Model d'estats invàlid")
    known = set(transitions)
    if initial not in known or not terminal or not set(terminal) <= known:
        raise UpdateModelError("Estats inicials o terminals invàlids")
    for source, targets in transitions.items():
        if not isinstance(targets, list) or len(targets) != len(set(targets)) or not set(targets) <= known or source in targets:
            raise UpdateModelError("Transició d'estat invàlida")
    reachable = {initial}
    while True:
        expanded = reachable | {target for source in reachable for target in transitions[source]}
        if expanded == reachable:
            break
        reachable = expanded
    if reachable != known:
        raise UpdateModelError("Hi ha estats inaccessibles")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"policy", "state"}:
        raise UpdateModelError("outputs incomplet")
    raw["outputs"] = {key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class UpdateModelPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "model_id": self.profile["model_id"],
            "hardware_profile": self.profile["hardware_profile"],
            "component_count": len(self.profile["components"]),
            "channel_count": len(self.profile["channels"]),
            "initial_state": self.profile["states"]["initial"],
        }


def create_update_model_plan(rootfs: Path, profile_path: Path) -> UpdateModelPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise UpdateModelError(f"Rootfs insegur: {root}")
    return UpdateModelPlan(root, load_update_model(profile_path))


class UpdateModelInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise UpdateModelError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: UpdateModelPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = (plan.output("policy"), plan.output("state"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(),
            "status": plan.profile["states"]["initial"],
            "current_version": None,
            "target_version": None,
            "channel": "production",
            "last_transition": None,
        }
        self._write(targets[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o644)
        self._write(targets[1], json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        return targets
