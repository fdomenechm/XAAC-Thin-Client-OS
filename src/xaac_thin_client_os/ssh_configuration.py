"""Restricted and temporarily activatable OpenSSH configuration (phase 7.7)."""
from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

import yaml


class SshConfigurationError(RuntimeError):
    """Raised when SSH cannot be configured safely."""


def _absolute(value: object, field: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise SshConfigurationError(f"{field} ha de ser una ruta")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise SshConfigurationError(f"Ruta SSH insegura: {field}")
    return path


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise SshConfigurationError(f"{name} ha de ser booleà")
    return value


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise SshConfigurationError(f"{name} ha d'estar entre {minimum} i {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class SshConfigurationPlan:
    rootfs: Path
    enabled: bool
    port: int
    allow_users: tuple[str, ...]
    allowed_sources: tuple[str, ...]
    public_key: bool
    password: bool
    keyboard_interactive: bool
    authorized_keys_directory: PurePosixPath
    allowed_key_types: tuple[str, ...]
    permit_root_login: bool
    x11_forwarding: bool
    tcp_forwarding: bool
    agent_forwarding: bool
    permit_tunnel: bool
    max_auth_tries: int
    login_grace_time: int
    client_alive_interval: int
    client_alive_count_max: int
    temporary_activation: bool
    default_duration_seconds: int
    minimum_duration_seconds: int
    maximum_duration_seconds: int
    state_path: PurePosixPath
    helper_path: PurePosixPath
    audit_rules_path: PurePosixPath
    log_level: str

    def root_path(self, path: PurePosixPath) -> Path:
        return self.rootfs / path.relative_to("/")

    def sshd_text(self) -> str:
        yesno = lambda value: "yes" if value else "no"
        key_file = f"{self.authorized_keys_directory}/%u"
        return "\n".join((
            "# Managed by XAAC Thin Client OS — phase 7.7",
            f"Port {self.port}", "AddressFamily any", "Protocol 2",
            f"PermitRootLogin {yesno(self.permit_root_login)}",
            f"PubkeyAuthentication {yesno(self.public_key)}",
            f"PasswordAuthentication {yesno(self.password)}",
            f"KbdInteractiveAuthentication {yesno(self.keyboard_interactive)}",
            f"AuthorizedKeysFile {key_file}",
            f"PubkeyAcceptedAlgorithms {','.join(self.allowed_key_types)}",
            "AuthenticationMethods publickey", "UsePAM yes",
            f"AllowUsers {' '.join(self.allow_users)}",
            f"X11Forwarding {yesno(self.x11_forwarding)}",
            f"AllowTcpForwarding {yesno(self.tcp_forwarding)}",
            f"AllowAgentForwarding {yesno(self.agent_forwarding)}",
            f"PermitTunnel {yesno(self.permit_tunnel)}",
            "PermitUserEnvironment no", "GatewayPorts no", "PermitEmptyPasswords no",
            "HostbasedAuthentication no", "IgnoreRhosts yes", "StrictModes yes",
            f"MaxAuthTries {self.max_auth_tries}", f"LoginGraceTime {self.login_grace_time}",
            f"ClientAliveInterval {self.client_alive_interval}",
            f"ClientAliveCountMax {self.client_alive_count_max}",
            f"LogLevel {self.log_level}", "",))

    def helper_text(self) -> str:
        return f'''#!/bin/sh
set -eu
action="${{1:-status}}"
duration="${{2:-{self.default_duration_seconds}}}"
state={self.state_path}
case "$action" in
  enable)
    case "$duration" in *[!0-9]*|'') echo 'Duració invàlida' >&2; exit 2;; esac
    [ "$duration" -ge {self.minimum_duration_seconds} ] && [ "$duration" -le {self.maximum_duration_seconds} ] || {{ echo 'Duració fora de política' >&2; exit 2; }}
    install -d -o root -g root -m 0750 "$(dirname "$state")"
    expires=$(date -u -d "+$duration seconds" +%Y-%m-%dT%H:%M:%SZ)
    printf '{{"schema_version":1,"status":"enabled","duration_seconds":%s,"expires_at":"%s"}}\n' "$duration" "$expires" > "$state.tmp"
    chmod 0640 "$state.tmp"; mv "$state.tmp" "$state"
    systemctl start ssh.service
    systemd-run --unit=xaac-ssh-expire --on-active="${{duration}}s" --property=Type=oneshot /usr/local/sbin/xaac-ssh-access disable
    logger -t xaac-ssh-access "temporary access enabled duration=${{duration}}"
    ;;
  disable)
    systemctl stop ssh.service
    printf '{{"schema_version":1,"status":"disabled"}}\n' > "$state.tmp"
    chmod 0640 "$state.tmp"; mv "$state.tmp" "$state"
    logger -t xaac-ssh-access 'temporary access disabled'
    ;;
  status) [ -r "$state" ] && cat "$state" || printf '{{"schema_version":1,"status":"disabled"}}\n' ;;
  *) echo 'Ús: xaac-ssh-access enable [segons]|disable|status' >&2; exit 2 ;;
esac
'''

    def audit_text(self) -> str:
        return (f"-w /etc/ssh/sshd_config.d/20-xaac-hardening.conf -p wa -k xaac-ssh-config\n"
                f"-w {self.authorized_keys_directory} -p wa -k xaac-ssh-keys\n"
                f"-w {self.helper_path} -p x -k xaac-ssh-access\n")

    def to_manifest(self) -> dict[str, object]:
        return {
            "rootfs": str(self.rootfs), "enabled": self.enabled, "port": self.port,
            "allow_users": list(self.allow_users), "allowed_sources": list(self.allowed_sources),
            "authentication": {"public_key": self.public_key, "password": self.password,
                "keyboard_interactive": self.keyboard_interactive,
                "authorized_keys_directory": str(self.authorized_keys_directory),
                "allowed_key_types": list(self.allowed_key_types)},
            "temporary_activation": {"enabled": self.temporary_activation,
                "default_duration_seconds": self.default_duration_seconds,
                "minimum_duration_seconds": self.minimum_duration_seconds,
                "maximum_duration_seconds": self.maximum_duration_seconds},
            "audit": {"rules_path": str(self.audit_rules_path), "log_level": self.log_level},
        }


@dataclass(frozen=True, slots=True)
class SshConfigurationResult:
    executed: bool
    log_path: Path
    files_written: tuple[Path, ...]


def create_ssh_configuration_plan(rootfs: Path, config_path: Path) -> SshConfigurationPlan:
    rootfs = rootfs.resolve()
    if rootfs == Path("/") or rootfs.parent == Path("/") or rootfs.name != "rootfs":
        raise SshConfigurationError("Ruta rootfs insegura")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SshConfigurationError(f"No es pot llegir {config_path}: {exc}") from exc
    expected = {"schema_version", "enabled", "port", "allow_users", "allowed_sources", "authentication", "hardening", "temporary_activation", "audit"}
    if not isinstance(raw, dict) or raw.get("schema_version") != 2 or set(raw) != expected:
        raise SshConfigurationError("config/ssh.yaml té un esquema no suportat")
    users = raw["allow_users"]
    if not isinstance(users, list) or not users:
        raise SshConfigurationError("allow_users ha de contindre almenys un usuari")
    clean_users = []
    for user in users:
        if not isinstance(user, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", user):
            raise SshConfigurationError(f"Usuari SSH no vàlid: {user}")
        if user in {"root", "xaac-kiosk", "xaac-agent"}:
            raise SshConfigurationError(f"Usuari SSH no autoritzat: {user}")
        clean_users.append(user)
    sources = raw["allowed_sources"]
    if not isinstance(sources, list) or not sources:
        raise SshConfigurationError("allowed_sources ha de contindre almenys una xarxa")
    clean_sources = []
    for source in sources:
        try:
            clean_sources.append(str(ipaddress.ip_network(source, strict=True)))
        except (TypeError, ValueError) as exc:
            raise SshConfigurationError(f"Xarxa SSH no vàlida: {source}") from exc
    auth, hard, temporary, audit = raw["authentication"], raw["hardening"], raw["temporary_activation"], raw["audit"]
    if not isinstance(auth, dict) or set(auth) != {"public_key", "password", "keyboard_interactive", "authorized_keys_directory", "allowed_key_types"}:
        raise SshConfigurationError("authentication no és vàlid")
    if not isinstance(hard, dict) or set(hard) != {"permit_root_login", "x11_forwarding", "tcp_forwarding", "agent_forwarding", "permit_tunnel", "max_auth_tries", "login_grace_time", "client_alive_interval", "client_alive_count_max"}:
        raise SshConfigurationError("hardening no és vàlid")
    if not isinstance(temporary, dict) or set(temporary) != {"enabled", "default_duration_seconds", "minimum_duration_seconds", "maximum_duration_seconds", "state_path", "helper_path"}:
        raise SshConfigurationError("temporary_activation no és vàlid")
    if not isinstance(audit, dict) or set(audit) != {"rules_path", "log_level"}:
        raise SshConfigurationError("audit no és vàlid")
    public_key = _boolean(auth["public_key"], "authentication.public_key")
    password = _boolean(auth["password"], "authentication.password")
    keyboard = _boolean(auth["keyboard_interactive"], "authentication.keyboard_interactive")
    if not public_key or password or keyboard:
        raise SshConfigurationError("SSH ha d'usar només autenticació per clau pública")
    key_types = auth["allowed_key_types"]
    supported = {"ssh-ed25519", "sk-ssh-ed25519@openssh.com", "rsa-sha2-512", "rsa-sha2-256"}
    if not isinstance(key_types, list) or not key_types or any(item not in supported for item in key_types):
        raise SshConfigurationError("Tipus de clau SSH no autoritzat")
    permit_root = _boolean(hard["permit_root_login"], "hardening.permit_root_login")
    if permit_root:
        raise SshConfigurationError("L'accés SSH de root ha d'estar desactivat")
    minimum = _integer(temporary["minimum_duration_seconds"], "minimum_duration_seconds", 30, 86400)
    maximum = _integer(temporary["maximum_duration_seconds"], "maximum_duration_seconds", minimum, 86400)
    default = _integer(temporary["default_duration_seconds"], "default_duration_seconds", minimum, maximum)
    log_level = audit["log_level"]
    if log_level not in {"VERBOSE", "INFO"}:
        raise SshConfigurationError("Nivell de registre SSH no autoritzat")
    return SshConfigurationPlan(
        rootfs, _boolean(raw["enabled"], "enabled"), _integer(raw["port"], "port", 1, 65535),
        tuple(dict.fromkeys(clean_users)), tuple(dict.fromkeys(clean_sources)), public_key, password, keyboard,
        _absolute(auth["authorized_keys_directory"], "authorized_keys_directory"), tuple(dict.fromkeys(key_types)),
        permit_root, _boolean(hard["x11_forwarding"], "hardening.x11_forwarding"),
        _boolean(hard["tcp_forwarding"], "hardening.tcp_forwarding"),
        _boolean(hard["agent_forwarding"], "hardening.agent_forwarding"),
        _boolean(hard["permit_tunnel"], "hardening.permit_tunnel"),
        _integer(hard["max_auth_tries"], "max_auth_tries", 1, 10),
        _integer(hard["login_grace_time"], "login_grace_time", 1, 600),
        _integer(hard["client_alive_interval"], "client_alive_interval", 0, 3600),
        _integer(hard["client_alive_count_max"], "client_alive_count_max", 0, 10),
        _boolean(temporary["enabled"], "temporary_activation.enabled"), default, minimum, maximum,
        _absolute(temporary["state_path"], "state_path"), _absolute(temporary["helper_path"], "helper_path"),
        _absolute(audit["rules_path"], "rules_path"), log_level)


class SshConfigurator:
    def __init__(self, *, geteuid: Callable[[], int] = os.geteuid) -> None:
        self._geteuid = geteuid

    @staticmethod
    def _write(path: Path, content: str, mode: int = 0o644) -> None:
        if path.is_symlink():
            raise SshConfigurationError(f"No es pot sobreescriure un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name("." + path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, path)

    def execute(self, plan: SshConfigurationPlan, log_path: Path, *, dry_run: bool = False) -> SshConfigurationResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        sshd = plan.rootfs / "etc/ssh/sshd_config.d/20-xaac-hardening.conf"
        sources = plan.rootfs / "etc/xaac/ssh-allowed-sources"
        keys_dir = plan.root_path(plan.authorized_keys_directory)
        helper = plan.root_path(plan.helper_path)
        audit = plan.root_path(plan.audit_rules_path)
        state = plan.root_path(plan.state_path)
        files = (sshd, sources, keys_dir, helper, audit, state)
        with log_path.open("w", encoding="utf-8") as log:
            log.write(("DRY-RUN" if dry_run else "EXECUTE") + " ssh configuration phase=7.7\n")
            log.write(f"port={plan.port}\ntemporary_activation={str(plan.temporary_activation).lower()}\n")
            for source in plan.allowed_sources:
                log.write(f"allowed_source={source}\n")
            if dry_run:
                return SshConfigurationResult(False, log_path, ())
            if self._geteuid() != 0:
                raise SshConfigurationError("La configuració real requereix privilegis de root")
            required = (plan.rootfs / "etc/debian_version", plan.rootfs / "usr/lib/systemd/system/ssh.service", plan.rootfs / "usr/sbin/sshd")
            missing = [str(path) for path in required if not path.exists()]
            if missing:
                raise SshConfigurationError("Al rootfs falten requisits: " + ", ".join(missing))
            self._write(sshd, plan.sshd_text())
            self._write(sources, "".join(f"{source}\n" for source in plan.allowed_sources), 0o640)
            if keys_dir.is_symlink():
                raise SshConfigurationError(f"Directori de claus insegur: {keys_dir}")
            keys_dir.mkdir(parents=True, exist_ok=True); keys_dir.chmod(0o750)
            for user in plan.allow_users:
                key_file = keys_dir / user
                if not key_file.exists():
                    self._write(key_file, "# Managed by XAAC Agent; add approved public keys only\n", 0o600)
            self._write(helper, plan.helper_text(), 0o750)
            self._write(audit, plan.audit_text(), 0o640)
            self._write(state, json.dumps({"schema_version": 1, "status": "disabled"}, sort_keys=True) + "\n", 0o640)
            wants = plan.rootfs / "etc/systemd/system/multi-user.target.wants"
            wants.mkdir(parents=True, exist_ok=True)
            link = wants / "ssh.service"
            if link.exists() or link.is_symlink():
                link.unlink()
            if plan.enabled:
                link.symlink_to("/usr/lib/systemd/system/ssh.service")
        return SshConfigurationResult(True, log_path, files)
