"""Package rollback policy and installer (phase 10.6)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class PackageRollbackError(RuntimeError):
    """Raised when package rollback configuration is unsafe."""


_UNIT = re.compile(r"^[A-Za-z0-9@_.-]+\.service$")


def _absolute_path(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or ".." in PurePosixPath(value).parts
    ):
        raise PackageRollbackError(f"Ruta insegura en {field}")
    return value


def load_package_rollback(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PackageRollbackError(f"No s'ha pogut carregar el rollback: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise PackageRollbackError("Política de rollback invàlida")
    if raw.get("hardware_profile") != "wyse3040":
        raise PackageRollbackError("Perfil de maquinari invàlid")
    if not isinstance(raw.get("rollback_id"), str) or not raw["rollback_id"].strip():
        raise PackageRollbackError("rollback_id invàlid")

    source = raw.get("source")
    required_source = {
        "require_failed_transaction": True,
        "require_recovery_point": True,
        "require_previous_versions": True,
    }
    if not isinstance(source, dict) or any(source.get(k) is not v for k, v in required_source.items()):
        raise PackageRollbackError("Origen de rollback insuficient")

    restore = raw.get("restore")
    required_restore = {
        "packages": True,
        "configuration": True,
        "transaction_state": True,
        "noninteractive": True,
    }
    if not isinstance(restore, dict) or any(restore.get(k) is not v for k, v in required_restore.items()):
        raise PackageRollbackError("Restauració incompleta")
    if not isinstance(restore.get("lock_timeout_seconds"), int) or not 1 <= restore["lock_timeout_seconds"] <= 3600:
        raise PackageRollbackError("Timeout de bloqueig invàlid")

    services = raw.get("services")
    if not isinstance(services, dict) or services.get("restart_only_affected") is not True:
        raise PackageRollbackError("Política de reinici invàlida")
    units = services.get("allowed_units")
    if (
        not isinstance(units, list)
        or not units
        or len(units) != len(set(units))
        or any(not isinstance(unit, str) or not _UNIT.fullmatch(unit) for unit in units)
    ):
        raise PackageRollbackError("Unitats systemd invàlides")

    validation = raw.get("validation")
    checks = {"packages", "configuration", "services", "client_session", "agent_health"}
    if (
        not isinstance(validation, dict)
        or validation.get("required") is not True
        or validation.get("fail_closed") is not True
        or set(validation.get("checks", [])) != checks
    ):
        raise PackageRollbackError("Validació de rollback invàlida")
    if not isinstance(validation.get("timeout_seconds"), int) or not 10 <= validation["timeout_seconds"] <= 1800:
        raise PackageRollbackError("Timeout de validació invàlid")

    blocked = raw.get("failed_versions")
    if (
        not isinstance(blocked, dict)
        or blocked.get("block") is not True
        or blocked.get("require_reason") is not True
        or blocked.get("require_transaction_id") is not True
    ):
        raise PackageRollbackError("Bloqueig de versions defectuoses invàlid")
    blocked["registry"] = _absolute_path(blocked.get("registry"), "failed_versions.registry")

    evidence = raw.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("preserve") is not True:
        raise PackageRollbackError("Política d'evidències invàlida")
    evidence["root"] = _absolute_path(evidence.get("root"), "evidence.root")

    outputs = raw.get("outputs")
    required_outputs = {"policy", "state", "runner", "service"}
    if not isinstance(outputs, dict) or set(outputs) != required_outputs:
        raise PackageRollbackError("outputs incomplet")
    raw["outputs"] = {
        key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()
    }
    return raw


@dataclass(frozen=True, slots=True)
class PackageRollbackPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "rollback_id": self.profile["rollback_id"],
            "hardware_profile": self.profile["hardware_profile"],
            "block_failed_versions": True,
            "validation_checks": self.profile["validation"]["checks"],
        }


def create_package_rollback_plan(rootfs: Path, profile_path: Path) -> PackageRollbackPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise PackageRollbackError(f"Rootfs insegur: {root}")
    return PackageRollbackPlan(root, load_package_rollback(profile_path))


class PackageRollbackInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise PackageRollbackError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: PackageRollbackPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in ("policy", "state", "runner", "service"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(),
            "status": "idle",
            "transaction_id": None,
            "failed_version": None,
            "restored_version": None,
            "recovery_point": None,
            "started_at": None,
            "completed_at": None,
            "restarted_services": [],
            "checks": {},
            "last_error": None,
        }
        runner = """#!/bin/sh
set -eu
POLICY=/etc/xaac/update/package-rollback.json
TRANSACTION=/var/lib/xaac-update/transaction-state.json
[ -r "$POLICY" ] || { echo "missing rollback policy" >&2; exit 2; }
[ -r "$TRANSACTION" ] || { echo "missing transaction state" >&2; exit 2; }
exec /usr/bin/xaac-update-service rollback-packages "$@"
"""
        service = """[Unit]
Description=XAAC package rollback
After=local-fs.target
ConditionPathExists=/var/lib/xaac-update/transaction-state.json

[Service]
Type=oneshot
ExecStart=/usr/libexec/xaac-update-rollback-packages
User=root
Group=root
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/xaac-update /var/cache/apt /var/lib/apt /var/lib/dpkg /etc/xaac
LockPersonality=yes
RestrictRealtime=yes
UMask=0027
"""
        self._write(targets[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[1], json.dumps(state, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[2], runner, 0o750)
        self._write(targets[3], service, 0o644)
        return targets
