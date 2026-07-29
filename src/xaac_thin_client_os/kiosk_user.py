"""Dedicated kiosk account policy and filesystem configuration."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class KioskUserError(RuntimeError):
    """Raised when the kiosk account policy is invalid or unsafe."""


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise KioskUserError(f"Ruta insegura: {name}")
    return path


def load_kiosk_user_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KioskUserError(f"No s'ha pogut carregar el perfil de quiosc: {exc}") from exc
    required = ("user", "permissions", "directories", "environment", "files")
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or any(not isinstance(raw.get(k), dict) for k in required):
        raise KioskUserError("Perfil d'usuari de quiosc invàlid")
    user = raw["user"]
    if user.get("name") != "xaac-kiosk" or user.get("group") != "xaac-kiosk":
        raise KioskUserError("El compte dedicat ha de ser xaac-kiosk")
    if user.get("shell") != "/usr/sbin/nologin" or user.get("locked") is not True or user.get("system") is not True:
        raise KioskUserError("El compte de quiosc ha de ser de sistema, bloquejat i no interactiu")
    home = _safe_absolute(user.get("home"), "user.home")
    if home != PurePosixPath("/var/lib/xaac-kiosk"):
        raise KioskUserError("Directori personal de quiosc no suportat")
    groups = user.get("supplementary_groups")
    allowed = {"audio", "video", "input", "render"}
    if not isinstance(groups, list) or not groups or set(groups) - allowed:
        raise KioskUserError("Grups suplementaris de quiosc no permesos")
    if str(raw["permissions"].get("home_mode")) != "0750":
        raise KioskUserError("El home del quiosc ha de tindre mode 0750")
    for section in ("persistent", "runtime"):
        values = raw["directories"].get(section)
        if not isinstance(values, list) or not values:
            raise KioskUserError(f"directories.{section} ha de ser una llista")
        for index, value in enumerate(values):
            _safe_absolute(value, f"directories.{section}[{index}]")
    environment = raw["environment"]
    required_env = {"HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"}
    if set(environment) != required_env:
        raise KioskUserError("Variables d'entorn del quiosc incompletes")
    for key, value in environment.items():
        _safe_absolute(value, f"environment.{key}")
    for name, value in raw["files"].items():
        _safe_absolute(value, f"files.{name}")
    return raw


@dataclass(frozen=True, slots=True)
class KioskUserPlan:
    rootfs: Path
    commands: tuple[tuple[str, ...], ...]
    directories: tuple[tuple[PurePosixPath, int], ...]
    files: tuple[tuple[PurePosixPath, str, int], ...]

    def to_manifest(self) -> dict[str, object]:
        return {
            "commands": [list(command) for command in self.commands],
            "directories": [str(path) for path, _ in self.directories],
            "files": [str(path) for path, _, _ in self.files],
        }


def create_kiosk_user_plan(rootfs: Path, profile_path: Path) -> KioskUserPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise KioskUserError(f"Rootfs insegur: {root}")
    profile = load_kiosk_user_profile(profile_path)
    user = profile["user"]
    groups = tuple(dict.fromkeys(user["supplementary_groups"]))
    commands = (
        ("chroot", str(root), "/usr/sbin/groupadd", "--system", "--force", user["group"]),
        ("chroot", str(root), "/usr/sbin/useradd", "--system", "--create-home", "--home-dir", user["home"], "--shell", user["shell"], "--gid", user["group"], "--groups", ",".join(groups), user["name"]),
        ("chroot", str(root), "/usr/sbin/usermod", "--lock", user["name"]),
    )
    dirs = tuple((_safe_absolute(p, "directory"), 0o750 if str(p).startswith(user["home"]) else 0o700) for p in profile["directories"]["persistent"] + profile["directories"]["runtime"])
    env = "".join(f"{key}={value}\n" for key, value in profile["environment"].items())
    tmp = (
        "d /var/lib/xaac-kiosk 0750 xaac-kiosk xaac-kiosk -\n"
        "d /var/lib/xaac-kiosk/.config 0750 xaac-kiosk xaac-kiosk -\n"
        "d /var/lib/xaac-kiosk/.local/state/xaac 0750 xaac-kiosk xaac-kiosk -\n"
        "d /run/user/xaac-kiosk 0700 xaac-kiosk xaac-kiosk -\n"
        "d /run/user/xaac-kiosk/cache 0700 xaac-kiosk xaac-kiosk -\n"
    )
    policy = json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    files = profile["files"]
    planned = (
        (_safe_absolute(files["environment"], "files.environment"), env, 0o640),
        (_safe_absolute(files["tmpfiles"], "files.tmpfiles"), tmp, 0o644),
        (_safe_absolute(files["policy"], "files.policy"), policy, 0o640),
    )
    return KioskUserPlan(root, commands, dirs, planned)


class KioskUserConfigurator:
    def execute(self, plan: KioskUserPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for rel, mode in plan.directories:
            target = plan.rootfs / str(rel).lstrip("/")
            if target.is_symlink():
                raise KioskUserError(f"No es gestionarà un enllaç simbòlic: {target}")
            target.mkdir(parents=True, exist_ok=True)
            target.chmod(mode)
        for rel, content, mode in plan.files:
            target = plan.rootfs / str(rel).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise KioskUserError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temp = target.with_name(target.name + ".tmp")
            temp.write_text(content, encoding="utf-8")
            temp.chmod(mode)
            temp.replace(target)
            written.append(target)
        return tuple(written)
