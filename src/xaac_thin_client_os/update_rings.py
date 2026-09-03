"""Update deployment rings policy and installer (phase 10.7)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class UpdateRingsError(RuntimeError):
    """Raised when update-ring configuration is unsafe or inconsistent."""


_ID = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_REQUIRED_RINGS = ("laboratory", "pilot", "production")
_ALLOWED_STATES = {"idle", "scheduled", "deploying", "paused", "completed", "cancelled", "failed"}
_TERMINAL_STATES = {"completed", "cancelled", "failed"}


def _absolute_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise UpdateRingsError(f"Ruta insegura en {field}")
    return value


def load_update_rings(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UpdateRingsError(f"No s'ha pogut carregar el desplegament per anells: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise UpdateRingsError("Política d'anells invàlida")
    if raw.get("hardware_profile") != "wyse3040":
        raise UpdateRingsError("Perfil de maquinari invàlid")
    if not isinstance(raw.get("deployment_id"), str) or not _ID.fullmatch(raw["deployment_id"]):
        raise UpdateRingsError("deployment_id invàlid")

    rings = raw.get("rings")
    if not isinstance(rings, list) or len(rings) != 3:
        raise UpdateRingsError("Calen exactament els anells laboratori, pilot i producció")
    ids, orders = [], []
    for ring in rings:
        if not isinstance(ring, dict) or not _ID.fullmatch(str(ring.get("id", ""))):
            raise UpdateRingsError("Anell invàlid")
        ids.append(ring["id"])
        orders.append(ring.get("order"))
        if ring.get("channel") != ring["id"]:
            raise UpdateRingsError("Canal incoherent amb l'anell")
        if not isinstance(ring.get("percentage"), int) or not 1 <= ring["percentage"] <= 100:
            raise UpdateRingsError("Percentatge d'anell invàlid")
        if not isinstance(ring.get("minimum_devices"), int) or ring["minimum_devices"] < 1:
            raise UpdateRingsError("Mínim de dispositius invàlid")
        if ring.get("automatic_promotion") is not False:
            raise UpdateRingsError("La promoció automàtica no està autoritzada")
    if tuple(ids) != _REQUIRED_RINGS or orders != sorted(orders) or len(set(orders)) != len(orders):
        raise UpdateRingsError("Ordre d'anells invàlid")

    promotion = raw.get("promotion")
    if not isinstance(promotion, dict) or any(promotion.get(k) is not True for k in (
        "sequential", "require_previous_ring_success", "require_manual_approval"
    )):
        raise UpdateRingsError("Promoció insuficientment controlada")
    if not isinstance(promotion.get("minimum_observation_minutes"), int) or not 1 <= promotion["minimum_observation_minutes"] <= 10080:
        raise UpdateRingsError("Període d'observació invàlid")
    success = promotion.get("success_threshold_percent")
    failure = promotion.get("maximum_failure_percent")
    if not isinstance(success, int) or not 1 <= success <= 100 or not isinstance(failure, int) or not 0 <= failure < 100 or success + failure > 100:
        raise UpdateRingsError("Llindars de promoció invàlids")

    controls = raw.get("controls")
    required_controls = {
        "pause_supported": True, "resume_supported": True, "cancellation_supported": True,
        "cancellation_blocks_new_installs": True, "allow_in_progress_completion": True,
    }
    if not isinstance(controls, dict) or any(controls.get(k) is not v for k, v in required_controls.items()):
        raise UpdateRingsError("Controls de pausa i cancel·lació incomplets")

    selection = raw.get("selection")
    required_selection = {
        "deterministic": True, "identity_field": "device_uuid",
        "algorithm": "sha256-modulo-100", "stable_across_checks": True,
    }
    if not isinstance(selection, dict) or any(selection.get(k) != v for k, v in required_selection.items()):
        raise UpdateRingsError("Selecció de dispositius invàlida")

    state = raw.get("state")
    if not isinstance(state, dict) or set(state.get("allowed", [])) != _ALLOWED_STATES or set(state.get("terminal", [])) != _TERMINAL_STATES:
        raise UpdateRingsError("Estats de desplegament invàlids")

    audit = raw.get("audit")
    if not isinstance(audit, dict) or any(audit.get(k) is not True for k in ("required", "record_actor", "record_reason", "record_timestamps")):
        raise UpdateRingsError("Auditoria insuficient")

    outputs = raw.get("outputs")
    required_outputs = {"policy", "state", "runner", "service"}
    if not isinstance(outputs, dict) or set(outputs) != required_outputs:
        raise UpdateRingsError("outputs incomplet")
    raw["outputs"] = {key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class UpdateRingsPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "deployment_id": self.profile["deployment_id"],
            "hardware_profile": self.profile["hardware_profile"],
            "rings": [ring["id"] for ring in self.profile["rings"]],
            "manual_promotion": True,
        }


def create_update_rings_plan(rootfs: Path, profile_path: Path) -> UpdateRingsPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise UpdateRingsError(f"Rootfs insegur: {root}")
    return UpdateRingsPlan(root, load_update_rings(profile_path))


class UpdateRingsInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise UpdateRingsError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def install(self, plan: UpdateRingsPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in ("policy", "state", "runner", "service"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(), "status": "idle", "current_ring": None,
            "target_version": None, "selected_percentage": 0, "actor": None,
            "reason": None, "paused_at": None, "cancelled_at": None,
            "started_at": None, "completed_at": None, "metrics": {}, "last_error": None,
        }
        runner = """#!/bin/sh
set -eu
POLICY=/etc/xaac/update/update-rings.json
STATE=/var/lib/xaac-update/ring-deployment-state.json
[ -r "$POLICY" ] || { echo "missing update-rings policy" >&2; exit 2; }
[ -r "$STATE" ] || { echo "missing update-rings state" >&2; exit 2; }
exec /usr/bin/xaac-update-service deploy-rings "$@"
"""
        service = """[Unit]
Description=XAAC staged update deployment by rings
After=network-online.target xaac-update.service
Wants=network-online.target
ConditionPathExists=/etc/xaac/update/update-rings.json

[Service]
Type=oneshot
ExecStart=/usr/libexec/xaac-update-rings
User=root
Group=root
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/xaac-update
LockPersonality=yes
RestrictRealtime=yes
UMask=0027
"""
        self._write(targets[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[1], json.dumps(state, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[2], runner, 0o750)
        self._write(targets[3], service, 0o644)
        return targets
