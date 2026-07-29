"""XMS and offline USB update sources (phase 10.8)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class UpdateSourcesError(RuntimeError):
    """Raised when XMS/USB update configuration is unsafe."""


_ID = re.compile(r"^[a-z][a-z0-9-]{1,47}$")
_ALLOWED_COMMANDS = {"check", "download", "stage", "install", "rollback", "cancel"}
_ALLOWED_STATES = {"idle", "received", "importing", "verified", "staged", "installing", "completed", "recovering", "cancelled", "failed"}


def _absolute(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise UpdateSourcesError(f"Ruta insegura en {field}")
    return value


def load_update_sources(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UpdateSourcesError(f"No s'ha pogut carregar la política XMS/USB: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise UpdateSourcesError("Política XMS/USB invàlida")
    if raw.get("policy_id") != "xaac-update-sources" or raw.get("hardware_profile") != "wyse3040":
        raise UpdateSourcesError("Identitat de política o perfil invàlid")

    xms = raw.get("xms")
    if not isinstance(xms, dict) or xms.get("enabled") is not True:
        raise UpdateSourcesError("Ordres XMS no habilitades")
    if set(xms.get("allowed_commands", [])) != _ALLOWED_COMMANDS:
        raise UpdateSourcesError("Conjunt d'ordres XMS invàlid")
    required_xms = ("require_enrolled_device", "require_authenticated_channel", "require_command_signature", "require_nonce", "reject_replay", "record_command_id")
    if any(xms.get(key) is not True for key in required_xms):
        raise UpdateSourcesError("Controls d'autenticació XMS incomplets")
    if not isinstance(xms.get("maximum_command_age_seconds"), int) or not 30 <= xms["maximum_command_age_seconds"] <= 3600:
        raise UpdateSourcesError("Caducitat d'ordre XMS invàlida")

    usb = raw.get("usb")
    if not isinstance(usb, dict) or usb.get("enabled") is not True:
        raise UpdateSourcesError("Actualització USB no habilitada")
    expected_usb = {
        "filesystem_read_only": True,
        "require_offline_manifest": True,
        "require_detached_signature": True,
        "require_sha256": True,
        "require_sha512": True,
        "reject_unknown_files": True,
        "copy_before_processing": True,
        "eject_after_import": True,
    }
    if any(usb.get(key) is not value for key, value in expected_usb.items()):
        raise UpdateSourcesError("Controls del paquet USB incomplets")
    label = usb.get("volume_label")
    if not isinstance(label, str) or not _ID.fullmatch(label):
        raise UpdateSourcesError("Etiqueta USB invàlida")
    if not isinstance(usb.get("maximum_package_mib"), int) or not 1 <= usb["maximum_package_mib"] <= 4096:
        raise UpdateSourcesError("Mida màxima USB invàlida")

    verification = raw.get("verification")
    required_verification = {
        "reuse_phase_10_4": True,
        "fail_closed": True,
        "require_authorized_keyring": True,
        "require_hardware_profile": True,
        "require_dependency_validation": True,
        "block_known_bad_versions": True,
    }
    if not isinstance(verification, dict) or any(verification.get(k) is not v for k, v in required_verification.items()):
        raise UpdateSourcesError("Verificació d'importació insuficient")

    recovery = raw.get("recovery")
    required_recovery = {
        "preserve_previous_staging": True,
        "quarantine_failed_import": True,
        "resume_interrupted_copy": False,
        "cleanup_partial_imports": True,
        "trigger_transactional_rollback": True,
    }
    if not isinstance(recovery, dict) or any(recovery.get(k) is not v for k, v in required_recovery.items()):
        raise UpdateSourcesError("Recuperació d'importació insuficient")

    audit = raw.get("audit")
    required_audit = ("required", "record_source", "record_actor", "record_device", "record_command_id", "record_hashes", "record_result", "record_timestamps")
    if not isinstance(audit, dict) or any(audit.get(k) is not True for k in required_audit):
        raise UpdateSourcesError("Auditoria XMS/USB insuficient")

    state = raw.get("state")
    if not isinstance(state, dict) or set(state.get("allowed", [])) != _ALLOWED_STATES or state.get("initial") != "idle":
        raise UpdateSourcesError("Màquina d'estats XMS/USB invàlida")

    outputs = raw.get("outputs")
    required_outputs = {"policy", "state", "audit_log", "inbox", "quarantine", "runner", "service", "udev_rule"}
    if not isinstance(outputs, dict) or set(outputs) != required_outputs:
        raise UpdateSourcesError("outputs incomplet")
    raw["outputs"] = {key: _absolute(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class UpdateSourcesPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {"schema_version": 1, "policy_id": self.profile["policy_id"], "hardware_profile": self.profile["hardware_profile"], "sources": ["xms", "usb"], "fail_closed": True}


def create_update_sources_plan(rootfs: Path, profile_path: Path) -> UpdateSourcesPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise UpdateSourcesError(f"Rootfs insegur: {root}")
    return UpdateSourcesPlan(root, load_update_sources(profile_path))


class UpdateSourcesInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise UpdateSourcesError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: UpdateSourcesPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        keys = ("policy", "state", "audit_log", "inbox", "quarantine", "runner", "service", "udev_rule")
        targets = tuple(plan.output(key) for key in keys)
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {**plan.manifest(), "status": "idle", "source": None, "actor": None, "command_id": None, "package_id": None, "target_version": None, "started_at": None, "completed_at": None, "recovery_required": False, "last_error": None}
        runner = """#!/bin/sh
set -eu
POLICY=/etc/xaac/update/update-sources.json
STATE=/var/lib/xaac-update/source-update-state.json
[ -r \"$POLICY\" ] || { echo \"missing update source policy\" >&2; exit 2; }
[ -r \"$STATE\" ] || { echo \"missing update source state\" >&2; exit 2; }
exec /usr/bin/xaac-update-service import-source \"$@\"
"""
        service = """[Unit]
Description=XAAC update import from XMS or signed USB media
After=network-online.target xaac-agent.service
ConditionPathExists=/etc/xaac/update/update-sources.json

[Service]
Type=oneshot
ExecStart=/usr/libexec/xaac-update-source-import
User=root
Group=root
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
PrivateDevices=no
ReadWritePaths=/var/lib/xaac-update /var/log/xaac
LockPersonality=yes
RestrictRealtime=yes
UMask=0027
"""
        udev = 'ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="xaac-update", TAG+="systemd", ENV{SYSTEMD_WANTS}+="xaac-update-source-import.service"\n'
        contents = (
            json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            "",
            "",
            "",
            runner,
            service,
            udev,
        )
        modes = (0o640, 0o640, 0o640, 0o750, 0o750, 0o750, 0o644, 0o644)
        for path, content, mode in zip(targets, contents, modes, strict=True):
            if path in (targets[3], targets[4]):
                if path.is_symlink():
                    raise UpdateSourcesError(f"Destinació amb enllaç simbòlic: {path}")
                path.mkdir(parents=True, exist_ok=True)
                os.chmod(path, mode)
            else:
                self._write(path, content, mode)
        return targets
