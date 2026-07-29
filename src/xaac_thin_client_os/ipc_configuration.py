"""Configure the authenticated local Client-Agent IPC channel (phase 6.5)."""
from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class IpcConfigurationError(RuntimeError):
    """Raised when the local IPC policy is invalid or unsafe."""


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise IpcConfigurationError(f"Ruta IPC insegura: {field}")
    return path


def _mode(value: object, field: str, *, socket_mode: bool = False) -> int:
    try:
        mode = int(str(value), 8)
    except ValueError as exc:
        raise IpcConfigurationError(f"Mode IPC invàlid: {field}") from exc
    if mode & 0o007 or (socket_mode and mode & 0o111):
        raise IpcConfigurationError(f"Mode IPC massa permissiu: {field}")
    return mode


def load_ipc_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise IpcConfigurationError(f"No s'ha pogut carregar el perfil IPC: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "transport", "protocol", "security", "paths"} or raw.get("schema_version") != 1:
        raise IpcConfigurationError("Esquema IPC invàlid")
    transport = raw["transport"]
    if not isinstance(transport, dict) or set(transport) != {"type", "path", "socket_mode", "owner", "group", "backlog"}:
        raise IpcConfigurationError("Transport IPC incomplet")
    if transport["type"] != "unix_socket":
        raise IpcConfigurationError("Només s'autoritza el transport unix_socket")
    socket_path = _absolute(transport["path"], "transport.path")
    if not str(socket_path).startswith("/run/xaac/") or socket_path.suffix != ".sock":
        raise IpcConfigurationError("El socket IPC ha d'estar dins de /run/xaac")
    _mode(transport["socket_mode"], "socket_mode", socket_mode=True)
    if not all(isinstance(transport[key], str) and transport[key] for key in ("owner", "group")):
        raise IpcConfigurationError("Propietari o grup IPC invàlid")
    if not isinstance(transport["backlog"], int) or not 1 <= transport["backlog"] <= 128:
        raise IpcConfigurationError("Backlog IPC invàlid")
    protocol = raw["protocol"]
    if not isinstance(protocol, dict) or set(protocol) != {"name", "version", "maximum_message_bytes", "request_timeout_seconds", "allowed_message_types"}:
        raise IpcConfigurationError("Protocol IPC incomplet")
    if protocol["version"] != 1 or not 1024 <= protocol["maximum_message_bytes"] <= 1048576:
        raise IpcConfigurationError("Límits o versió del protocol IPC invàlids")
    messages = protocol["allowed_message_types"]
    if not isinstance(messages, list) or not messages or len(messages) != len(set(messages)) or not all(isinstance(v, str) and v.isidentifier() for v in messages):
        raise IpcConfigurationError("Tipus de missatge IPC invàlids")
    security = raw["security"]
    if not isinstance(security, dict) or set(security) != {"client_user", "agent_user", "require_peer_credentials", "reject_unknown_messages", "runtime_directory_mode"}:
        raise IpcConfigurationError("Seguretat IPC incompleta")
    if security["require_peer_credentials"] is not True or security["reject_unknown_messages"] is not True:
        raise IpcConfigurationError("L'autenticació local i el rebuig de missatges desconeguts són obligatoris")
    _mode(security["runtime_directory_mode"], "runtime_directory_mode")
    paths = raw["paths"]
    if not isinstance(paths, dict) or set(paths) != {"configuration", "tmpfiles", "manifest"}:
        raise IpcConfigurationError("Rutes IPC incompletes")
    for key, value in paths.items():
        _absolute(value, f"paths.{key}")
    return raw


@dataclass(frozen=True, slots=True)
class IpcEnvelope:
    message_type: str
    request_id: str
    protocol_version: int
    payload: dict[str, Any]

    def encode(self, profile: dict[str, Any]) -> bytes:
        if self.message_type not in profile["protocol"]["allowed_message_types"]:
            raise IpcConfigurationError(f"Tipus de missatge IPC no autoritzat: {self.message_type}")
        if self.protocol_version != profile["protocol"]["version"] or not self.request_id:
            raise IpcConfigurationError("Versió o identificador de petició IPC invàlid")
        data = json.dumps({"type": self.message_type, "request_id": self.request_id, "version": self.protocol_version, "payload": self.payload}, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
        if len(data) > profile["protocol"]["maximum_message_bytes"]:
            raise IpcConfigurationError("Missatge IPC massa gran")
        return data

    @classmethod
    def decode(cls, data: bytes, profile: dict[str, Any]) -> "IpcEnvelope":
        if len(data) > profile["protocol"]["maximum_message_bytes"]:
            raise IpcConfigurationError("Missatge IPC massa gran")
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IpcConfigurationError("Missatge IPC malformat") from exc
        if not isinstance(value, dict) or set(value) != {"type", "request_id", "version", "payload"} or not isinstance(value["payload"], dict):
            raise IpcConfigurationError("Esquema de missatge IPC invàlid")
        envelope = cls(value["type"], value["request_id"], value["version"], value["payload"])
        envelope.encode(profile)
        return envelope


def peer_credentials(connection: socket.socket) -> tuple[int, int, int]:
    """Return Linux SO_PEERCRED (pid, uid, gid) for local authentication."""
    if not hasattr(socket, "SO_PEERCRED"):
        raise IpcConfigurationError("SO_PEERCRED no està disponible")
    import struct
    return struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))


class IpcConfigurator:
    def install(self, rootfs: Path, profile_path: Path, *, dry_run: bool = False) -> tuple[Path, ...]:
        root = rootfs.resolve()
        if root == Path("/") or root.parent == Path("/"):
            raise IpcConfigurationError(f"Rootfs insegur: {root}")
        profile = load_ipc_profile(profile_path)
        destinations = tuple(root / _absolute(value, key).relative_to("/") for key, value in profile["paths"].items())
        for destination in destinations:
            if destination.is_symlink():
                raise IpcConfigurationError(f"No s'utilitzarà un enllaç simbòlic: {destination}")
        if dry_run:
            return destinations
        configuration, tmpfiles, manifest = destinations
        for destination in destinations:
            destination.parent.mkdir(parents=True, exist_ok=True)
        configuration.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
        configuration.chmod(0o640)
        runtime = PurePosixPath(profile["transport"]["path"]).parent
        t = profile["transport"]
        tmpfiles.write_text(f"d {runtime} {profile['security']['runtime_directory_mode']} {t['owner']} {t['group']} -\n", encoding="utf-8")
        tmpfiles.chmod(0o644)
        manifest.write_text(json.dumps({"schema_version": 1, "transport": "unix_socket", "socket": t["path"], "protocol": profile["protocol"]["name"], "protocol_version": profile["protocol"]["version"], "authentication": "SO_PEERCRED", "allowed_messages": profile["protocol"]["allowed_message_types"]}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest.chmod(0o640)
        return destinations
