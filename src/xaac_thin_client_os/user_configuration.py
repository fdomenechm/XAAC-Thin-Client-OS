"""Deterministic users and groups configuration for the Debian rootfs."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml


class UserConfigurationError(RuntimeError):
    """Raised when users and groups cannot be configured safely."""


_NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


@dataclass(frozen=True, slots=True)
class GroupSpec:
    name: str
    system: bool


@dataclass(frozen=True, slots=True)
class UserSpec:
    name: str
    gecos: str
    primary_group: str
    supplementary_groups: tuple[str, ...]
    shell: str
    home: str
    system: bool
    locked: bool


@dataclass(frozen=True, slots=True)
class UserConfigurationPlan:
    rootfs: Path
    groups: tuple[GroupSpec, ...]
    users: tuple[UserSpec, ...]

    def commands(self) -> tuple[tuple[str, ...], ...]:
        commands: list[tuple[str, ...]] = []
        for group in self.groups:
            command = ["chroot", str(self.rootfs), "/usr/sbin/groupadd"]
            if group.system:
                command.append("--system")
            command.extend(["--force", group.name])
            commands.append(tuple(command))
        for user in self.users:
            command = ["chroot", str(self.rootfs), "/usr/sbin/useradd"]
            if user.system:
                command.append("--system")
            command.extend([
                "--create-home", "--home-dir", user.home,
                "--shell", user.shell, "--gid", user.primary_group,
                "--comment", user.gecos,
            ])
            if user.supplementary_groups:
                command.extend(["--groups", ",".join(user.supplementary_groups)])
            command.append(user.name)
            commands.append(tuple(command))
            if user.locked:
                commands.append(("chroot", str(self.rootfs), "/usr/sbin/usermod", "--lock", user.name))
        return tuple(commands)

    def to_manifest(self) -> dict[str, object]:
        return {
            "rootfs": str(self.rootfs),
            "groups": [{"name": item.name, "system": item.system} for item in self.groups],
            "users": [
                {
                    "name": item.name,
                    "gecos": item.gecos,
                    "primary_group": item.primary_group,
                    "supplementary_groups": list(item.supplementary_groups),
                    "shell": item.shell,
                    "home": item.home,
                    "system": item.system,
                    "locked": item.locked,
                }
                for item in self.users
            ],
            "commands": [list(item) for item in self.commands()],
        }


@dataclass(frozen=True, slots=True)
class UserConfigurationResult:
    executed: bool
    log_path: Path
    commands_executed: int


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UserConfigurationError(f"{name} ha de ser text no buit")
    return value.strip()


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise UserConfigurationError(f"{name} ha de ser booleà")
    return value


def _safe_name(value: object, name: str) -> str:
    text = _text(value, name)
    if not _NAME_RE.fullmatch(text):
        raise UserConfigurationError(f"{name} no és vàlid")
    return text


def _absolute_path(value: object, name: str) -> str:
    text = _text(value, name)
    path = Path(text)
    if not path.is_absolute() or ".." in path.parts:
        raise UserConfigurationError(f"{name} ha de ser una ruta absoluta segura")
    return text


def create_user_configuration_plan(rootfs: Path, config_path: Path) -> UserConfigurationPlan:
    rootfs = rootfs.resolve()
    if rootfs == Path("/") or rootfs.name != "rootfs" or rootfs.parent.parent.name != "runs":
        raise UserConfigurationError("Ruta rootfs insegura")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UserConfigurationError(f"No es pot llegir {config_path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise UserConfigurationError("config/users.yaml té un esquema no suportat")
    unknown = set(raw) - {"schema_version", "groups", "users"}
    if unknown:
        raise UserConfigurationError(f"Claus desconegudes en users.yaml: {', '.join(sorted(unknown))}")
    raw_groups = raw.get("groups")
    raw_users = raw.get("users")
    if not isinstance(raw_groups, list) or not isinstance(raw_users, list):
        raise UserConfigurationError("groups i users han de ser llistes")
    groups: list[GroupSpec] = []
    for index, item in enumerate(raw_groups):
        if not isinstance(item, dict) or set(item) - {"name", "system"}:
            raise UserConfigurationError(f"Grup {index} no vàlid")
        groups.append(GroupSpec(_safe_name(item.get("name"), "group.name"), _boolean(item.get("system"), "group.system")))
    group_names = [item.name for item in groups]
    if len(group_names) != len(set(group_names)):
        raise UserConfigurationError("Hi ha grups duplicats")
    users: list[UserSpec] = []
    for index, item in enumerate(raw_users):
        expected = {"name", "gecos", "primary_group", "supplementary_groups", "shell", "home", "system", "locked"}
        if not isinstance(item, dict) or set(item) != expected:
            raise UserConfigurationError(f"Usuari {index} no vàlid")
        supplementary = item["supplementary_groups"]
        if not isinstance(supplementary, list):
            raise UserConfigurationError("supplementary_groups ha de ser una llista")
        supplementary_names = tuple(_safe_name(value, "supplementary_group") for value in supplementary)
        primary = _safe_name(item["primary_group"], "primary_group")
        if primary not in group_names:
            raise UserConfigurationError(f"El grup primari {primary} no està declarat")
        users.append(UserSpec(
            _safe_name(item["name"], "user.name"),
            _text(item["gecos"], "user.gecos"),
            primary,
            tuple(dict.fromkeys(supplementary_names)),
            _absolute_path(item["shell"], "user.shell"),
            _absolute_path(item["home"], "user.home"),
            _boolean(item["system"], "user.system"),
            _boolean(item["locked"], "user.locked"),
        ))
    user_names = [item.name for item in users]
    if len(user_names) != len(set(user_names)):
        raise UserConfigurationError("Hi ha usuaris duplicats")
    if any(not item.locked for item in users):
        raise UserConfigurationError("Tots els comptes inicials han d'estar bloquejats")
    return UserConfigurationPlan(rootfs, tuple(groups), tuple(users))


class UserConfigurator:
    def __init__(self, *, geteuid: Callable[[], int] = os.geteuid, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self._geteuid = geteuid
        self._runner = runner

    def execute(self, plan: UserConfigurationPlan, log_path: Path, *, dry_run: bool = False) -> UserConfigurationResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        commands = plan.commands()
        with log_path.open("w", encoding="utf-8") as log:
            log.write(("DRY-RUN" if dry_run else "EXECUTE") + " user configuration\n")
            for command in commands:
                log.write("command=" + " ".join(command) + "\n")
            if dry_run:
                return UserConfigurationResult(False, log_path, 0)
            if self._geteuid() != 0:
                raise UserConfigurationError("La configuració real requereix privilegis de root")
            required = [plan.rootfs / "etc/debian_version", plan.rootfs / "usr/sbin/groupadd", plan.rootfs / "usr/sbin/useradd", plan.rootfs / "usr/sbin/usermod"]
            for user in plan.users:
                required.append(plan.rootfs / user.shell.lstrip("/"))
            missing = sorted({str(path) for path in required if not path.exists()})
            if missing:
                raise UserConfigurationError("Al rootfs falten requisits: " + ", ".join(missing))
            count = 0
            for command in commands:
                try:
                    self._runner(command, check=True, stdout=log, stderr=subprocess.STDOUT, text=True)
                except subprocess.CalledProcessError as exc:
                    raise UserConfigurationError(f"L'ordre ha fallat amb codi {exc.returncode}: {' '.join(command)}") from exc
                except OSError as exc:
                    raise UserConfigurationError(f"No s'ha pogut executar {' '.join(command)}: {exc}") from exc
                count += 1
        return UserConfigurationResult(True, log_path, count)
