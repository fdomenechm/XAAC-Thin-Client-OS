"""Dedicated graphical session manager configuration for the XAAC kiosk."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class SessionManagerError(RuntimeError):
    """Raised for invalid or unsafe session-manager configuration."""


@dataclass(frozen=True, slots=True)
class SessionInventory:
    manager_running: bool
    active_user: str | None
    session_name: str | None
    backend: str | None
    autologin: bool
    interactive_greeter: bool
    competing_managers: tuple[str, ...]
    restart_count: int


@dataclass(frozen=True, slots=True)
class SessionCheck:
    name: str
    status: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "expected": self.expected, "actual": self.actual}


@dataclass(frozen=True, slots=True)
class SessionReport:
    profile: str
    compatible: bool
    checks: tuple[SessionCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {"profile": self.profile, "compatible": self.compatible, "checks": [c.to_dict() for c in self.checks]}


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise SessionManagerError(f"Ruta insegura: {name}")
    return path


def load_session_manager_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SessionManagerError(f"No s'ha pogut carregar el perfil de sessió: {exc}") from exc
    required = ("manager", "session", "autologin", "restrictions", "packages", "files")
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or any(not isinstance(raw.get(k), dict) for k in required):
        raise SessionManagerError("Perfil de gestor de sessió invàlid o esquema no suportat")
    if raw["manager"].get("name") != "greetd":
        raise SessionManagerError("greetd és el gestor de sessió controlat")
    session = raw["session"]
    if session.get("name") != "xaac-kiosk" or session.get("user") != "xaac-kiosk":
        raise SessionManagerError("La sessió dedicada ha de pertànyer a xaac-kiosk")
    if session.get("backend") not in {"wayland", "x11"}:
        raise SessionManagerError("Backend de sessió no suportat")
    if raw["autologin"].get("enabled") is not True:
        raise SessionManagerError("L'autologin del quiosc ha d'estar habilitat")
    restrictions = raw["restrictions"]
    if restrictions.get("allowed_user") != "xaac-kiosk" or restrictions.get("allow_other_sessions") is not False or restrictions.get("allow_interactive_greeter") is not False:
        raise SessionManagerError("Les restriccions de sessió no són segures")
    if int(restrictions.get("vt", 0)) < 1 or int(restrictions.get("vt", 0)) > 6:
        raise SessionManagerError("VT de sessió invàlid")
    packages = raw["packages"].get("required")
    if not isinstance(packages, list) or "greetd" not in packages or not all(isinstance(x, str) and x for x in packages):
        raise SessionManagerError("Paquets del gestor de sessió invàlids")
    for name, value in raw["files"].items():
        _safe_absolute(value, name)
    return raw


def compare_session(inv: SessionInventory, profile: dict[str, Any]) -> SessionReport:
    checks: list[SessionCheck] = []

    def add(name: str, ok: bool, expected: object, actual: object) -> None:
        checks.append(SessionCheck(name, "pass" if ok else "fail", str(expected), str(actual)))

    add("manager", inv.manager_running, True, inv.manager_running)
    add("user", inv.active_user == profile["session"]["user"], profile["session"]["user"], inv.active_user)
    add("session", inv.session_name == profile["session"]["name"], profile["session"]["name"], inv.session_name)
    add("backend", inv.backend == profile["session"]["backend"], profile["session"]["backend"], inv.backend)
    add("autologin", inv.autologin, True, inv.autologin)
    add("greeter", not inv.interactive_greeter, False, inv.interactive_greeter)
    add("competing-managers", not inv.competing_managers, (), inv.competing_managers)
    add("restart", inv.restart_count <= 5, "<=5", inv.restart_count)
    return SessionReport(str(profile.get("profile", "xaac-kiosk-session")), all(c.status == "pass" for c in checks), tuple(checks))


@dataclass(frozen=True, slots=True)
class SessionManagerPlan:
    rootfs: Path
    packages: tuple[str, ...]
    forbidden_packages: tuple[str, ...]
    files: tuple[tuple[PurePosixPath, str, int], ...]

    def to_manifest(self) -> dict[str, object]:
        return {"packages": list(self.packages), "forbidden_packages": list(self.forbidden_packages), "files": [str(p) for p, _, _ in self.files]}


def create_session_manager_plan(rootfs: Path, profile_path: Path) -> SessionManagerPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise SessionManagerError(f"Rootfs insegur: {root}")
    p = load_session_manager_profile(profile_path)
    files = p["files"]
    user = p["session"]["user"]
    command = p["session"]["command"]
    vt = int(p["restrictions"]["vt"])
    greetd = (
        "[terminal]\n"
        f"vt = {vt}\n\n"
        "[default_session]\n"
        f'command = "{command}"\n'
        f'user = "{user}"\n'
    )
    launcher = (
        "#!/bin/sh\n"
        "set -eu\n"
        "export XDG_SESSION_TYPE=wayland\n"
        "export XDG_CURRENT_DESKTOP=XAAC\n"
        "export XDG_SESSION_DESKTOP=xaac-kiosk\n"
        "export GDK_BACKEND=wayland,x11\n"
        "if [ -x /usr/bin/labwc ] && [ -e /dev/dri/card0 ]; then\n"
        "    export XDG_SESSION_TYPE=wayland\n"
        "    exec /usr/bin/labwc --config /etc/xaac/labwc/rc.xml\n"
        "fi\n"
        "export XDG_SESSION_TYPE=x11\n"
        "export GDK_BACKEND=x11\n"
        "exec /usr/bin/startx /usr/bin/openbox -- -nolisten tcp -nocursor vt1\n"
    )
    desktop = (
        "[Desktop Entry]\n"
        "Name=XAAC Kiosk\n"
        "Comment=Dedicated XAAC Thin Client session\n"
        f"Exec={command}\n"
        "Type=Application\n"
        "DesktopNames=XAAC\n"
    )
    environment = (
        "XDG_SESSION_TYPE=wayland\n"
        "XDG_CURRENT_DESKTOP=XAAC\n"
        "XDG_SESSION_DESKTOP=xaac-kiosk\n"
        "GDK_BACKEND=wayland,x11\n"
    )
    policy = json.dumps({"manager": p["manager"], "session": p["session"], "autologin": p["autologin"], "restrictions": p["restrictions"]}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    planned = (
        (_safe_absolute(files["greetd_config"], "greetd_config"), greetd, 0o600),
        (_safe_absolute(files["session_launcher"], "session_launcher"), launcher, 0o755),
        (_safe_absolute(files["wayland_session"], "wayland_session"), desktop, 0o644),
        (_safe_absolute(files["environment"], "environment"), environment, 0o644),
        (_safe_absolute(files["policy"], "policy"), policy, 0o644),
    )
    return SessionManagerPlan(root, tuple(dict.fromkeys(p["packages"]["required"])), tuple(dict.fromkeys(p["packages"].get("forbidden", []))), planned)


class SessionManagerConfigurator:
    def execute(self, plan: SessionManagerPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for rel, content, mode in plan.files:
            target = plan.rootfs / str(rel).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise SessionManagerError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temp = target.with_name(target.name + ".tmp")
            temp.write_text(content, encoding="utf-8")
            temp.chmod(mode)
            temp.replace(target)
            written.append(target)
        return tuple(written)
