"""Build-time installation of the phase 10.2 transactional update runtime."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class TransactionalUpdateError(RuntimeError):
    """Raised when the transactional update policy is unsafe."""


def _path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise TransactionalUpdateError(f"Ruta insegura en {field}")
    return value


def load_transactional_update(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TransactionalUpdateError(f"No s'ha pogut carregar la política transaccional: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 2:
        raise TransactionalUpdateError("Política transaccional invàlida")
    if raw.get("transaction_id") != "xaac-transactional-update" or raw.get("hardware_profile") != "wyse3040":
        raise TransactionalUpdateError("Identitat transaccional invàlida")

    staging = raw.get("staging")
    if not isinstance(staging, dict):
        raise TransactionalUpdateError("Staging invàlid")
    staging["root"] = _path(staging.get("root"), "staging.root")
    if not isinstance(staging.get("maximum_bundle_bytes"), int) or not 16 * 1024 * 1024 <= staging["maximum_bundle_bytes"] <= 1024 * 1024 * 1024:
        raise TransactionalUpdateError("Mida màxima de bundle invàlida")
    if staging.get("preserve_on_success") is not False:
        raise TransactionalUpdateError("El staging ha de netejar-se després de confirmar")

    recovery = raw.get("recovery_point")
    if not isinstance(recovery, dict) or recovery.get("required") is not True:
        raise TransactionalUpdateError("Punt de recuperació obligatori")
    for key in ("root", "package_cache"):
        recovery[key] = _path(recovery.get(key), f"recovery_point.{key}")
    if recovery.get("include_package_state") is not True or recovery.get("include_configuration") is not True:
        raise TransactionalUpdateError("Punt de recuperació incomplet")
    if not isinstance(recovery.get("max_points"), int) or not 1 <= recovery["max_points"] <= 4:
        raise TransactionalUpdateError("Retenció de recuperació invàlida")
    config_paths = recovery.get("configuration_paths")
    if not isinstance(config_paths, list) or not config_paths:
        raise TransactionalUpdateError("Rutes de configuració absents")
    recovery["configuration_paths"] = [_path(value, "recovery_point.configuration_paths") for value in config_paths]

    installation = raw.get("installation")
    if not isinstance(installation, dict) or any(
        installation.get(key) is not True
        for key in ("require_verified_staging", "atomic_component_set", "noninteractive")
    ):
        raise TransactionalUpdateError("Instal·lació insegura")
    if not isinstance(installation.get("lock_timeout_seconds"), int) or not 30 <= installation["lock_timeout_seconds"] <= 1800:
        raise TransactionalUpdateError("Timeout d'instal·lació invàlid")

    health = raw.get("health")
    expected_checks = {
        "exact_package_versions", "dpkg_audit", "apt_check", "executables",
        "previously_active_services", "previously_running_thin_client",
    }
    if (
        not isinstance(health, dict)
        or health.get("required") is not True
        or health.get("fail_closed") is not True
        or set(health.get("checks", [])) != expected_checks
    ):
        raise TransactionalUpdateError("Health-check invàlid")
    if not isinstance(health.get("timeout_seconds"), int) or not 30 <= health["timeout_seconds"] <= 1800:
        raise TransactionalUpdateError("Timeout de health-check invàlid")

    failure = raw.get("failure")
    if not isinstance(failure, dict) or any(
        failure.get(key) is not True for key in ("mark_failed", "preserve_evidence", "automatic_rollback")
    ):
        raise TransactionalUpdateError("Gestió de fallada invàlida")
    interruption = raw.get("interruption")
    if not isinstance(interruption, dict) or interruption.get("rollback_on_boot") is not True:
        raise TransactionalUpdateError("Recuperació d'interrupcions invàlida")
    if set(interruption.get("states", [])) != {"installing", "validating", "rolling_back"}:
        raise TransactionalUpdateError("Estats d'interrupció invàlids")

    outputs = raw.get("outputs")
    required = {"policy", "state", "runtime", "recovery_service", "tmpfiles"}
    if not isinstance(outputs, dict) or set(outputs) != required:
        raise TransactionalUpdateError("outputs incomplet")
    raw["outputs"] = {key: _path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class TransactionalUpdatePlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "transaction_id": self.profile["transaction_id"],
            "hardware_profile": self.profile["hardware_profile"],
            "automatic_rollback": True,
            "recovery_points": self.profile["recovery_point"]["max_points"],
            "health_checks": self.profile["health"]["checks"],
        }


def create_transactional_update_plan(rootfs: Path, profile_path: Path) -> TransactionalUpdatePlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise TransactionalUpdateError(f"Rootfs insegur: {root}")
    return TransactionalUpdatePlan(root, load_transactional_update(profile_path))


class TransactionalUpdateInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise TransactionalUpdateError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: TransactionalUpdatePlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in ("policy", "state", "recovery_service", "tmpfiles"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(),
            "status": "idle",
            "transaction_id_value": None,
            "started_at": None,
            "completed_at": None,
            "recovery_point": None,
            "target_os_version": None,
            "changed_packages": [],
            "restarted": [],
            "checks": {},
            "last_error": None,
        }
        service = """[Unit]\nDescription=Recover interrupted XAAC update transaction\nDefaultDependencies=no\nAfter=local-fs.target\nBefore=greetd.service xaac-vpn-manager.service\nConditionPathExists=/var/lib/xaac-update/transaction-state.json\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /usr/local/libexec/xaac_update_runtime.py recover-interrupted\nUser=root\nGroup=root\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=yes\nProtectSystem=no\nLockPersonality=yes\nRestrictRealtime=yes\nUMask=0077\n\n[Install]\nWantedBy=multi-user.target\n"""
        staging = plan.profile["staging"]["root"]
        recovery = plan.profile["recovery_point"]["root"]
        cache = plan.profile["recovery_point"]["package_cache"]
        tmpfiles = (
            "d /var/lib/xaac-update 0750 root root -\n"
            f"d {staging} 0700 root root -\n"
            f"d {recovery} 0700 root root -\n"
            f"d {cache} 0700 root root -\n"
            "d /var/log/xaac 0750 root root -\n"
        )
        self._write(targets[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[1], json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[2], service, 0o644)
        self._write(targets[3], tmpfiles, 0o644)
        return targets
