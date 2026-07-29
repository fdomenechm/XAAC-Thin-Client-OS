"""Safe XMS device enrollment state machine (phase 6.8)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import yaml


class XmsEnrollmentError(RuntimeError):
    """Raised when XMS enrollment data or state is invalid or unsafe."""


_TOKEN = re.compile(r"^[A-Za-z0-9._~-]{16,512}$")
_DEVICE_ID = re.compile(r"^[0-9a-fA-F-]{32,36}$")


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
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "enrollment", "paths"} or raw.get("schema_version") != 1:
        raise XmsEnrollmentError("Esquema d'enrolament XMS invàlid")
    enrollment = raw["enrollment"]
    required = {"format", "version", "server_url", "approval_required", "certificate_renewal_days", "safe_failure"}
    if not isinstance(enrollment, dict) or set(enrollment) != required:
        raise XmsEnrollmentError("Configuració d'enrolament incompleta")
    if enrollment["format"] != "xaac-xms-enrollment" or enrollment["version"] != 1:
        raise XmsEnrollmentError("Format o versió d'enrolament no compatible")
    url = enrollment["server_url"]
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > 2048:
        raise XmsEnrollmentError("L'URL d'XMS ha d'utilitzar HTTPS")
    if enrollment["approval_required"] is not True or enrollment["safe_failure"] is not True:
        raise XmsEnrollmentError("L'aprovació i l'error segur són obligatoris")
    days = enrollment["certificate_renewal_days"]
    if not isinstance(days, int) or not 1 <= days <= 365:
        raise XmsEnrollmentError("Finestra de renovació invàlida")
    paths = raw["paths"]
    if not isinstance(paths, dict) or set(paths) != {"identity", "state", "request", "certificate", "ca_certificate", "manifest"}:
        raise XmsEnrollmentError("Rutes d'enrolament incompletes")
    for key, value in paths.items():
        _absolute(value, f"paths.{key}")
    return raw


class XmsEnrollmentManager:
    """Manage local enrollment lifecycle without exposing enrollment secrets."""

    def __init__(self, rootfs: Path, profile_path: Path, *, now: Callable[[], datetime] | None = None):
        self.root = rootfs.resolve()
        if self.root == Path("/") or self.root.parent == Path("/"):
            raise XmsEnrollmentError(f"Rootfs insegur: {self.root}")
        self.profile = load_xms_enrollment_profile(profile_path)
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _path(self, name: str) -> Path:
        return self.root / _absolute(self.profile["paths"][name], name).relative_to("/")

    def _timestamp(self) -> str:
        return self.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
        if path.is_symlink():
            raise XmsEnrollmentError(f"No s'utilitzarà un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, path)

    def _identity(self) -> dict[str, Any]:
        path = self._path("identity")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise XmsEnrollmentError("La identitat persistent no està disponible") from exc
        device_id = data.get("uuid") or data.get("device_uuid")
        if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id):
            raise XmsEnrollmentError("UUID de dispositiu invàlid")
        return data

    def install(self, *, dry_run: bool = False) -> tuple[Path, ...]:
        paths = tuple(self._path(name) for name in ("state", "request", "manifest"))
        for path in paths:
            if path.is_symlink():
                raise XmsEnrollmentError(f"No s'utilitzarà un enllaç simbòlic: {path}")
        if dry_run:
            return paths
        manifest = {
            "schema_version": 1,
            "format": "xaac-xms-enrollment",
            "version": 1,
            "states": ["unenrolled", "pending_approval", "enrolled", "renewal_pending", "error"],
            "server_url": self.profile["enrollment"]["server_url"],
        }
        self._atomic_json(paths[0], {"schema_version": 1, "status": "unenrolled", "updated_at": self._timestamp()}, 0o600)
        self._atomic_json(paths[2], manifest, 0o640)
        return paths

    def request_enrollment(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise XmsEnrollmentError("Token d'enrolament invàlid")
        identity = self._identity()
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        request = {
            "schema_version": 1,
            "device_uuid": identity.get("uuid") or identity.get("device_uuid"),
            "hostname": identity.get("hostname", "unknown"),
            "server_url": self.profile["enrollment"]["server_url"],
            "token_sha256": token_hash,
            "requested_at": self._timestamp(),
        }
        self._atomic_json(self._path("request"), request, 0o600)
        state = {"schema_version": 1, "status": "pending_approval", "updated_at": request["requested_at"], "device_uuid": request["device_uuid"]}
        self._atomic_json(self._path("state"), state, 0o600)
        return state

    def approve(self, certificate_pem: str, ca_certificate_pem: str) -> dict[str, Any]:
        if "BEGIN CERTIFICATE" not in certificate_pem or "BEGIN CERTIFICATE" not in ca_certificate_pem:
            raise XmsEnrollmentError("Certificat d'enrolament invàlid")
        state_path = self._path("state")
        try:
            current = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise XmsEnrollmentError("Estat d'enrolament no disponible") from exc
        if current.get("status") not in {"pending_approval", "renewal_pending"}:
            raise XmsEnrollmentError("L'enrolament no està pendent d'aprovació")
        for name, content in (("certificate", certificate_pem), ("ca_certificate", ca_certificate_pem)):
            path = self._path(name)
            if path.is_symlink():
                raise XmsEnrollmentError(f"No s'utilitzarà un enllaç simbòlic: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.tmp")
            temp.write_text(content.rstrip() + "\n", encoding="utf-8")
            temp.chmod(0o600 if name == "certificate" else 0o644)
            os.replace(temp, path)
        state = {"schema_version": 1, "status": "enrolled", "updated_at": self._timestamp(), "device_uuid": current.get("device_uuid")}
        self._atomic_json(state_path, state, 0o600)
        self._path("request").unlink(missing_ok=True)
        return state

    def request_renewal(self) -> dict[str, Any]:
        state_path = self._path("state")
        try:
            current = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise XmsEnrollmentError("Estat d'enrolament no disponible") from exc
        if current.get("status") != "enrolled" or not self._path("certificate").is_file():
            raise XmsEnrollmentError("El dispositiu no està enrolat")
        state = {**current, "status": "renewal_pending", "updated_at": self._timestamp()}
        self._atomic_json(state_path, state, 0o600)
        return state

    def unenroll(self) -> dict[str, Any]:
        for name in ("request", "certificate", "ca_certificate"):
            path = self._path(name)
            if path.is_symlink():
                raise XmsEnrollmentError(f"No s'eliminarà un enllaç simbòlic: {path}")
            path.unlink(missing_ok=True)
        state = {"schema_version": 1, "status": "unenrolled", "updated_at": self._timestamp()}
        self._atomic_json(self._path("state"), state, 0o600)
        return state

    def record_safe_error(self, reason: str) -> dict[str, Any]:
        clean = " ".join(str(reason).split())[:256]
        if not clean:
            raise XmsEnrollmentError("Motiu d'error buit")
        state = {"schema_version": 1, "status": "error", "safe": True, "reason": clean, "updated_at": self._timestamp()}
        self._atomic_json(self._path("state"), state, 0o600)
        return state
