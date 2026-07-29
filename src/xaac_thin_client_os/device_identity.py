"""Persistent device identity generation for XAAC Thin Client OS (phase 6.3)."""
from __future__ import annotations

import json
import re
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class DeviceIdentityError(RuntimeError):
    """Raised when identity configuration or material is invalid."""


Runner = Callable[..., subprocess.CompletedProcess[str]]
_MAC = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SERIAL = re.compile(r"^[A-Za-z0-9_.:+/-]{1,128}$")


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise DeviceIdentityError(f"Ruta insegura: {field}")
    return path


def load_device_identity_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DeviceIdentityError(f"No s'ha pogut carregar el perfil d'identitat: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "identity", "sources", "security"} or raw.get("schema_version") != 1:
        raise DeviceIdentityError("Esquema d'identitat invàlid")
    identity = raw["identity"]
    required = {"state_path", "certificate_path", "private_key_path", "certificate_days", "hostname_prefix", "hostname_path", "machine_id_path"}
    if not isinstance(identity, dict) or set(identity) != required:
        raise DeviceIdentityError("Configuració d'identitat incompleta")
    for key in ("state_path", "certificate_path", "private_key_path", "hostname_path", "machine_id_path"):
        _absolute(identity[key], key)
    if not isinstance(identity["certificate_days"], int) or not 30 <= identity["certificate_days"] <= 36500:
        raise DeviceIdentityError("Duració del certificat invàlida")
    if not _HOST.fullmatch(str(identity["hostname_prefix"])):
        raise DeviceIdentityError("Prefix de hostname invàlid")
    sources = raw["sources"]
    if not isinstance(sources, dict) or set(sources) != {"serial_paths", "mac_root"} or not isinstance(sources["serial_paths"], list) or not sources["serial_paths"]:
        raise DeviceIdentityError("Fonts d'identitat incompletes")
    for value in sources["serial_paths"]:
        _absolute(value, "serial_paths")
    _absolute(sources["mac_root"], "mac_root")
    security = raw["security"]
    if not isinstance(security, dict) or set(security) != {"state_mode", "certificate_mode", "private_key_mode", "directory_mode", "allowed_group"}:
        raise DeviceIdentityError("Política de seguretat incompleta")
    for key in ("state_mode", "certificate_mode", "private_key_mode", "directory_mode"):
        try:
            mode = int(str(security[key]), 8)
        except ValueError as exc:
            raise DeviceIdentityError(f"Mode invàlid: {key}") from exc
        if mode & 0o002:
            raise DeviceIdentityError(f"Mode massa permissiu: {key}")
    return raw


def _under(root: Path, value: object) -> Path:
    return root / _absolute(value, "path").relative_to("/")


def _read_serial(rootfs: Path, paths: list[str]) -> str:
    invalid = {"", "none", "unknown", "to be filled by o.e.m.", "default string"}
    for value in paths:
        path = _under(rootfs, value)
        if path.is_file() and not path.is_symlink():
            serial = path.read_text(encoding="utf-8", errors="replace").strip()
            if serial.lower() not in invalid and _SERIAL.fullmatch(serial):
                return serial
    raise DeviceIdentityError("No s'ha pogut obtindre un número de sèrie fiable")


def _read_mac(rootfs: Path, mac_root: str) -> str:
    base = _under(rootfs, mac_root)
    if not base.is_dir() or base.is_symlink():
        raise DeviceIdentityError("No existeix una arrel de xarxa segura")
    candidates: list[str] = []
    for interface in sorted(base.iterdir(), key=lambda item: item.name):
        if interface.name == "lo":
            continue
        address = interface / "address"
        if address.is_file():
            mac = address.read_text(encoding="ascii", errors="ignore").strip().lower()
            if _MAC.fullmatch(mac) and mac != "00:00:00:00:00:00" and not (int(mac.split(":")[0], 16) & 1):
                candidates.append(mac)
    if not candidates:
        raise DeviceIdentityError("No s'ha trobat cap adreça MAC vàlida")
    return candidates[0]


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    uuid: str
    serial: str
    mac: str
    hostname: str
    certificate: str

    def to_dict(self) -> dict[str, str]:
        return {"schema_version": "1", "uuid": self.uuid, "serial": self.serial, "mac": self.mac, "hostname": self.hostname, "certificate": self.certificate}


class DeviceIdentityManager:
    """Create or validate one immutable, persistent device identity."""

    def create(self, rootfs: Path, profile_path: Path, *, dry_run: bool = False, runner: Runner = subprocess.run) -> DeviceIdentity:
        root = rootfs.resolve()
        if root == Path("/") or root.parent == Path("/"):
            raise DeviceIdentityError(f"Rootfs insegur: {root}")
        profile = load_device_identity_profile(profile_path)
        cfg, sources, security = profile["identity"], profile["sources"], profile["security"]
        state = _under(root, cfg["state_path"])
        cert = _under(root, cfg["certificate_path"])
        key = _under(root, cfg["private_key_path"])
        hostname_path = _under(root, cfg["hostname_path"])
        machine_id = _under(root, cfg["machine_id_path"])
        for path in (state, cert, key, hostname_path, machine_id):
            if path.is_symlink():
                raise DeviceIdentityError(f"No s'utilitzarà un enllaç simbòlic: {path}")
        if state.exists():
            return self._load_existing(state, cert, key)
        serial = _read_serial(root, sources["serial_paths"])
        mac = _read_mac(root, sources["mac_root"])
        device_uuid = str(uuid.uuid4())
        hostname = f"{cfg['hostname_prefix']}-{device_uuid.split('-')[0]}"
        if not _HOST.fullmatch(hostname):
            raise DeviceIdentityError("Hostname generat invàlid")
        identity = DeviceIdentity(device_uuid, serial, mac, hostname, str(cfg["certificate_path"]))
        if dry_run:
            return identity
        for directory in {state.parent, cert.parent, key.parent, hostname_path.parent, machine_id.parent}:
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(int(security["directory_mode"], 8))
        hostname_path.write_text(hostname + "\n", encoding="utf-8")
        hostname_path.chmod(0o644)
        if not machine_id.exists() or not machine_id.read_text(encoding="ascii", errors="ignore").strip():
            machine_id.write_text(device_uuid.replace("-", "") + "\n", encoding="ascii")
            machine_id.chmod(0o444)
        try:
            runner(("openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", str(cfg["certificate_days"]), "-subj", f"/CN={device_uuid}/serialNumber={serial}", "-addext", f"subjectAltName=URI:urn:xaac:device:{device_uuid}", "-keyout", str(key), "-out", str(cert)), check=True, text=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            key.unlink(missing_ok=True); cert.unlink(missing_ok=True)
            raise DeviceIdentityError(f"No s'ha pogut generar el certificat: {exc}") from exc
        if not cert.is_file() or not key.is_file():
            raise DeviceIdentityError("OpenSSL no ha generat el certificat i la clau")
        cert.chmod(int(security["certificate_mode"], 8)); key.chmod(int(security["private_key_mode"], 8))
        tmp = state.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(identity.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.chmod(int(security["state_mode"], 8)); tmp.replace(state)
        return identity

    @staticmethod
    def _load_existing(state: Path, cert: Path, key: Path) -> DeviceIdentity:
        try:
            raw = json.loads(state.read_text(encoding="utf-8"))
            identity = DeviceIdentity(str(raw["uuid"]), str(raw["serial"]), str(raw["mac"]), str(raw["hostname"]), str(raw["certificate"]))
            uuid.UUID(identity.uuid)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise DeviceIdentityError("Identitat persistent invàlida") from exc
        if not _SERIAL.fullmatch(identity.serial) or not _MAC.fullmatch(identity.mac) or not _HOST.fullmatch(identity.hostname):
            raise DeviceIdentityError("Camps de la identitat persistent invàlids")
        if not cert.is_file() or cert.is_symlink() or not key.is_file() or key.is_symlink():
            raise DeviceIdentityError("Material criptogràfic persistent absent o insegur")
        return identity
