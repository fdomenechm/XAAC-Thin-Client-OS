"""XAAC Agent XMS-enrollment integration contract (Block 7.5)."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class XmsEnrollmentError(RuntimeError):
    """Raised when the OS/Agent enrollment contract is invalid or unsafe."""


_ALLOWED_COMMANDS = ("provision", "enable", "disable", "status", "unenroll")


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise XmsEnrollmentError(f"Ruta d'enrolament insegura: {field}")
    return path


def load_xms_enrollment_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise XmsEnrollmentError(f"No s'ha pogut carregar el perfil d'enrolament: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "enrollment", "manifest"} or raw.get("schema_version") != 3:
        raise XmsEnrollmentError("Esquema d'enrolament XMS invàlid")

    enrollment = raw.get("enrollment")
    required = {
        "format", "version", "admin_command", "admin_target", "service_unit", "configuration",
        "bootstrap_token", "device_credentials", "registration_state", "require_https",
        "bootstrap_token_one_time", "explicit_reenrollment", "commands",
    }
    if not isinstance(enrollment, dict) or set(enrollment) != required:
        raise XmsEnrollmentError("Configuració d'enrolament incompleta")
    if enrollment["format"] != "xaac-agent-admin" or enrollment["version"] != 1:
        raise XmsEnrollmentError("Format o versió d'enrolament no compatible")
    for field in ("admin_command", "admin_target", "configuration", "bootstrap_token", "device_credentials", "registration_state"):
        _absolute(enrollment[field], f"enrollment.{field}")
    if enrollment["admin_command"] != "/usr/sbin/xaac-agent-admin":
        raise XmsEnrollmentError("L'eina administrativa XMS no és la suportada")
    if enrollment["admin_target"] != "/opt/xaac-agent/runtime/bin/xaac-agent-admin":
        raise XmsEnrollmentError("El target de xaac-agent-admin no és el suportat")
    if enrollment["service_unit"] != "xaac-agent.service":
        raise XmsEnrollmentError("La unitat de l'Agent no és la suportada")
    if enrollment["require_https"] is not True:
        raise XmsEnrollmentError("HTTPS és obligatori per a XMS")
    if enrollment["bootstrap_token_one_time"] is not True:
        raise XmsEnrollmentError("El token d'enrolament ha de ser d'un sol ús local")
    if enrollment["explicit_reenrollment"] is not True:
        raise XmsEnrollmentError("El reenrolament ha de requerir una acció local explícita")
    commands = enrollment["commands"]
    if not isinstance(commands, list) or tuple(commands) != _ALLOWED_COMMANDS:
        raise XmsEnrollmentError("Superfície administrativa d'enrolament no vàlida")

    manifest = raw.get("manifest")
    if not isinstance(manifest, dict) or set(manifest) != {"path", "mode"}:
        raise XmsEnrollmentError("Manifest d'enrolament incomplet")
    _absolute(manifest["path"], "manifest.path")
    if manifest["path"] != "/etc/xaac/xms-enrollment-manifest.json" or str(manifest["mode"]) != "0640":
        raise XmsEnrollmentError("Manifest d'enrolament insegur")
    return raw


class XmsEnrollmentManager:
    """Install only the OS-side contract; the Agent owns the enrollment lifecycle."""

    def __init__(self, rootfs: Path, profile_path: Path):
        self.root = rootfs.resolve()
        if self.root == Path("/") or self.root.parent == Path("/"):
            raise XmsEnrollmentError(f"Rootfs insegur: {self.root}")
        self.profile = load_xms_enrollment_profile(profile_path)

    def _path(self, value: object) -> Path:
        return self.root / _absolute(value, "path").relative_to("/")

    def install(self, *, dry_run: bool = False) -> tuple[Path, ...]:
        enrollment = self.profile["enrollment"]
        manifest_cfg = self.profile["manifest"]
        manifest_path = self._path(manifest_cfg["path"])
        if manifest_path.is_symlink():
            raise XmsEnrollmentError(f"No s'utilitzarà un enllaç simbòlic: {manifest_path}")
        if dry_run:
            return (manifest_path,)

        admin = self._path(enrollment["admin_command"])
        admin_target = self._path(enrollment["admin_target"])
        config = self._path(enrollment["configuration"])
        service = self.root / "usr/lib/systemd/system" / enrollment["service_unit"]
        if admin.is_symlink():
            try:
                link_target = os.readlink(admin)
            except OSError as exc:
                raise XmsEnrollmentError("No s'ha pogut inspeccionar xaac-agent-admin") from exc
            if link_target != enrollment["admin_target"]:
                raise XmsEnrollmentError("xaac-agent-admin apunta fora del runtime autoritzat")
            admin_ok = admin_target.is_file() and os.access(admin_target, os.X_OK)
        else:
            admin_ok = admin.is_file() and os.access(admin, os.X_OK)
        if not admin_ok:
            raise XmsEnrollmentError("xaac-agent-admin no està instal·lat o no és executable")
        if not config.is_file():
            raise XmsEnrollmentError("La configuració de XAAC Agent no està instal·lada")
        if not service.is_file():
            raise XmsEnrollmentError("La unitat systemd de XAAC Agent no està instal·lada")

        payload = {
            "schema_version": 1,
            "contract": "xaac-agent-admin/v1",
            "managed_by": "xaac-agent.deb",
            "admin_command": enrollment["admin_command"],
            "admin_target": enrollment["admin_target"],
            "service_unit": enrollment["service_unit"],
            "configuration": enrollment["configuration"],
            "bootstrap": {
                "token_path": enrollment["bootstrap_token"],
                "one_time": True,
                "accepted_cli_secret_argument": False,
                "require_https": True,
            },
            "state": {
                "device_credentials": enrollment["device_credentials"],
                "registration": enrollment["registration_state"],
            },
            "explicit_reenrollment": True,
            "commands": list(_ALLOWED_COMMANDS),
        }
        self._atomic_json(manifest_path, payload, int(str(manifest_cfg["mode"]), 8))
        return (manifest_path,)

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any], mode: int) -> None:
        if path.is_symlink():
            raise XmsEnrollmentError(f"No s'utilitzarà un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            temporary.chmod(mode)
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise XmsEnrollmentError(f"No s'ha pogut escriure el manifest d'enrolament: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)
