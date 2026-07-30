"""Safe package repair policy for phase 11.3."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class PackageRepairError(RuntimeError):
    """Raised when the package repair policy is incomplete or unsafe."""


_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
_ALLOWED_VALIDATIONS = {"dpkg-audit", "apt-check", "package-files", "xaac-services"}
_ALLOWED_EVENTS = {"repair_started", "repair_completed", "repair_failed"}


def _absolute_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise PackageRepairError(f"Ruta insegura en {field}")
    return value


def _positive_int(value: object, field: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise PackageRepairError(f"Valor invàlid en {field}")
    return value


def load_package_repair(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PackageRepairError(f"No s'ha pogut carregar la reparació de paquets: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise PackageRepairError("Política de reparació de paquets invàlida")
    if raw.get("hardware_profile") != "wyse3040":
        raise PackageRepairError("Perfil de maquinari no suportat")
    if not isinstance(raw.get("repair_id"), str) or not raw["repair_id"].strip():
        raise PackageRepairError("repair_id invàlid")

    packages = raw.get("packages")
    managed = packages.get("managed") if isinstance(packages, dict) else None
    if not isinstance(managed, list) or not managed or len(managed) != len(set(managed)):
        raise PackageRepairError("Llista de paquets gestionats invàlida")
    if any(not isinstance(item, str) or not _PACKAGE.fullmatch(item) for item in managed):
        raise PackageRepairError("Nom de paquet invàlid")
    if packages.get("require_installed") is not True or packages.get("allow_additional_dependencies") is not True:
        raise PackageRepairError("Controls de paquets incomplets")

    verification = raw.get("verification")
    if not isinstance(verification, dict):
        raise PackageRepairError("Verificació absent")
    for key in ("apt_check", "dpkg_audit", "verify_package_files", "require_signed_repository", "fail_closed"):
        if verification.get(key) is not True:
            raise PackageRepairError(f"Control obligatori desactivat: verification.{key}")

    repair = raw.get("repair")
    if not isinstance(repair, dict):
        raise PackageRepairError("Configuració de reparació absent")
    for key in ("reinstall_managed_packages", "repair_dependencies", "restore_configuration", "preserve_local_overrides", "atomic_configuration_restore"):
        if repair.get(key) is not True:
            raise PackageRepairError(f"Control obligatori desactivat: repair.{key}")
    _positive_int(repair.get("max_attempts"), "repair.max_attempts", 5)
    _positive_int(repair.get("timeout_seconds"), "repair.timeout_seconds", 3600)

    configuration = raw.get("configuration")
    if not isinstance(configuration, dict):
        raise PackageRepairError("Configuració de restauració absent")
    configuration["backup_directory"] = _absolute_path(configuration.get("backup_directory"), "configuration.backup_directory")
    configuration["staging_directory"] = _absolute_path(configuration.get("staging_directory"), "configuration.staging_directory")
    protected = configuration.get("protected_paths")
    if not isinstance(protected, list) or not protected or len(protected) != len(set(protected)):
        raise PackageRepairError("Rutes protegides invàlides")
    configuration["protected_paths"] = [_absolute_path(item, "configuration.protected_paths") for item in protected]

    final = raw.get("final_validation")
    commands = final.get("commands") if isinstance(final, dict) else None
    if not isinstance(commands, list) or set(commands) != _ALLOWED_VALIDATIONS or len(commands) != len(set(commands)):
        raise PackageRepairError("Validació final incompleta")
    if final.get("require_all") is not True:
        raise PackageRepairError("La validació final ha de requerir totes les comprovacions")

    diagnostics = raw.get("diagnostics")
    if not isinstance(diagnostics, dict) or diagnostics.get("preserve_on_success") is not True:
        raise PackageRepairError("Diagnòstics insegurs")
    diagnostics["output_directory"] = _absolute_path(diagnostics.get("output_directory"), "diagnostics.output_directory")

    notifications = raw.get("notifications")
    if not isinstance(notifications, dict) or set(notifications.get("destinations", [])) != {"agent", "xms"}:
        raise PackageRepairError("Cal notificar Agent i XMS")
    events = notifications.get("notify_on")
    if not isinstance(events, list) or set(events) != _ALLOWED_EVENTS or len(events) != len(set(events)):
        raise PackageRepairError("Esdeveniments de notificació incomplets")

    safety = raw.get("safety")
    if not isinstance(safety, dict) or safety.get("automatic_factory_reset") is not False:
        raise PackageRepairError("El factory reset automàtic està prohibit")
    for key in ("destructive_actions_require_confirmation", "preserve_evidence"):
        if safety.get(key) is not True:
            raise PackageRepairError(f"Control de seguretat obligatori desactivat: {key}")

    outputs = raw.get("outputs")
    required = {"policy", "state", "runner", "service"}
    if not isinstance(outputs, dict) or set(outputs) != required:
        raise PackageRepairError("outputs incomplet")
    raw["outputs"] = {key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class PackageRepairPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "repair_id": self.profile["repair_id"],
            "hardware_profile": self.profile["hardware_profile"],
            "managed_packages": tuple(self.profile["packages"]["managed"]),
            "validation_count": len(self.profile["final_validation"]["commands"]),
            "max_attempts": self.profile["repair"]["max_attempts"],
        }


def create_package_repair_plan(rootfs: Path, profile_path: Path) -> PackageRepairPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise PackageRepairError(f"Rootfs insegur: {root}")
    return PackageRepairPlan(root, load_package_repair(profile_path))


class PackageRepairInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise PackageRepairError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: PackageRepairPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in ("policy", "state", "runner", "service"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(),
            "status": "idle",
            "attempt": 0,
            "started_at": None,
            "completed_at": None,
            "reinstalled_packages": [],
            "dependencies_repaired": False,
            "configuration_restored": False,
            "final_validation": None,
            "diagnostic_bundle": None,
            "last_error": None,
        }
        runner = """#!/bin/sh
set -eu
POLICY=/etc/xaac/recovery/package-repair.json
STATE=/var/lib/xaac-recovery/package-repair-state.json
[ -r "$POLICY" ] || { echo "missing package repair policy" >&2; exit 2; }
[ -r "$STATE" ] || { echo "missing package repair state" >&2; exit 2; }
exec /usr/bin/xaac-agent recovery packages "$@"
"""
        service = """[Unit]
Description=XAAC package repair
After=network-online.target xaac-agent.service
Wants=network-online.target
ConditionPathExists=/etc/xaac/recovery/package-repair.json

[Service]
Type=oneshot
ExecStart=/usr/libexec/xaac-package-repair repair
User=root
Group=root
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/xaac-recovery /var/cache/apt /var/lib/apt /var/lib/dpkg /etc/xaac
LockPersonality=yes
RestrictRealtime=yes
UMask=0027
"""
        self._write(targets[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[1], json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[2], runner, 0o750)
        self._write(targets[3], service, 0o644)
        return targets
