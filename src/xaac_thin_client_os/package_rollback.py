"""Build-time validation and state installation for phase 10.2 rollback."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class PackageRollbackError(RuntimeError):
    """Raised when rollback policy is unsafe."""


def _path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise PackageRollbackError(f"Ruta insegura en {field}")
    return value


def load_package_rollback(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PackageRollbackError(f"No s'ha pogut carregar el rollback: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 2 or raw.get("hardware_profile") != "wyse3040":
        raise PackageRollbackError("Política de rollback invàlida")
    source = raw.get("source")
    if not isinstance(source, dict) or any(
        source.get(key) is not True
        for key in ("require_recovery_point", "require_previous_versions", "allow_last_confirmed_transaction")
    ):
        raise PackageRollbackError("Origen de rollback insuficient")
    restore = raw.get("restore")
    if not isinstance(restore, dict) or any(
        restore.get(key) is not True
        for key in ("packages", "configuration", "transaction_state", "noninteractive")
    ):
        raise PackageRollbackError("Restauració incompleta")
    validation = raw.get("validation")
    if not isinstance(validation, dict) or validation.get("required") is not True or validation.get("fail_closed") is not True:
        raise PackageRollbackError("Validació de rollback invàlida")
    blocked = raw.get("failed_versions")
    if not isinstance(blocked, dict) or any(
        blocked.get(key) is not True for key in ("block", "require_reason", "require_transaction_id")
    ):
        raise PackageRollbackError("Bloqueig de versions defectuoses invàlid")
    blocked["registry"] = _path(blocked.get("registry"), "failed_versions.registry")
    evidence = raw.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("preserve") is not True:
        raise PackageRollbackError("Política d'evidències invàlida")
    evidence["root"] = _path(evidence.get("root"), "evidence.root")
    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"policy", "state"}:
        raise PackageRollbackError("outputs incomplet")
    raw["outputs"] = {key: _path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class PackageRollbackPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "rollback_id": self.profile["rollback_id"],
            "hardware_profile": self.profile["hardware_profile"],
            "block_failed_versions": True,
            "manual_rollback": True,
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
        targets = (plan.output("policy"), plan.output("state"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(),
            "status": "idle",
            "transaction_id": None,
            "completed_at": None,
            "restored_packages": {},
            "checks": {},
            "last_error": None,
        }
        self._write(targets[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[1], json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        return targets
