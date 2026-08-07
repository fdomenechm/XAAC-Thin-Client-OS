"""Secure launcher configuration for XAAC Thin Client."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class ThinClientLauncherError(RuntimeError):
    """Raised for invalid or unsafe launcher configuration."""


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise ThinClientLauncherError(f"Ruta insegura: {name}")
    return path


def load_thin_client_launcher_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ThinClientLauncherError(f"No s'ha pogut carregar el perfil: {exc}") from exc
    required = ("application", "launch", "packages", "files")
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or any(
        not isinstance(raw.get(key), dict) for key in required
    ):
        raise ThinClientLauncherError("Perfil de llançament invàlid o esquema no suportat")
    app = raw["application"]
    if app.get("user") != "xaac-kiosk":
        raise ThinClientLauncherError("El client ha d'executar-se com xaac-kiosk")
    if set(app) != {"user", "executable", "configuration_directory"}:
        raise ThinClientLauncherError("Configuració de l'aplicació incompleta")
    _safe_absolute(app.get("executable"), "executable")
    _safe_absolute(app.get("configuration_directory"), "configuration_directory")
    launch = raw["launch"]
    if launch.get("prevent_duplicates") is not True or launch.get("backend") not in {"wayland", "x11"}:
        raise ThinClientLauncherError("Política de llançament insegura")
    _safe_absolute(launch.get("command"), "command")
    _safe_absolute(launch.get("lock_file"), "lock_file")
    packages = raw["packages"].get("required")
    if not isinstance(packages, list) or "python3" not in packages or "gir1.2-gtk-4.0" not in packages:
        raise ThinClientLauncherError("Dependències obligatòries incompletes")
    for name, value in raw["files"].items():
        _safe_absolute(value, name)
    return raw


@dataclass(frozen=True, slots=True)
class ThinClientLauncherPlan:
    rootfs: Path
    packages: tuple[str, ...]
    files: tuple[tuple[PurePosixPath, str, int], ...]

    def to_manifest(self) -> dict[str, object]:
        return {"packages": list(self.packages), "files": [str(path) for path, _, _ in self.files]}


def create_thin_client_launcher_plan(rootfs: Path, profile_path: Path) -> ThinClientLauncherPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise ThinClientLauncherError(f"Rootfs insegur: {root}")
    profile = load_thin_client_launcher_profile(profile_path)
    app = profile["application"]
    launch = profile["launch"]
    files = profile["files"]
    launcher = f'''#!/bin/sh
set -eu
EXECUTABLE={app["executable"]!s}
CONFIG_DIR={app["configuration_directory"]!s}
LOCK={launch["lock_file"]!s}

[ -x "$EXECUTABLE" ] || {{ echo "XAAC Thin Client no està instal·lat" >&2; exit 69; }}
[ -d "$CONFIG_DIR" ] || {{ echo "Configuració de XAAC Thin Client absent" >&2; exit 78; }}
exec /usr/bin/flock -n "$LOCK" "$EXECUTABLE"
'''
    environment = (
        "PYTHONUNBUFFERED=1\n"
        "PYTHONDONTWRITEBYTECODE=1\n"
        "GDK_BACKEND=wayland,x11\n"
        "XDG_CURRENT_DESKTOP=XAAC\n"
        f"XAAC_LOG_IDENTIFIER={launch['log_identifier']}\n"
    )
    policy = json.dumps(
        {"application": app, "launch": launch, "logging": {"destination": "journald", "identifier": launch["log_identifier"]}},
        ensure_ascii=False, indent=2, sort_keys=True,
    ) + "\n"
    planned = (
        (_safe_absolute(files["launcher"], "launcher"), launcher, 0o755),
        (_safe_absolute(files["environment"], "environment"), environment, 0o644),
        (_safe_absolute(files["policy"], "policy"), policy, 0o644),
    )
    return ThinClientLauncherPlan(root, tuple(dict.fromkeys(profile["packages"]["required"])), planned)


class ThinClientLauncherConfigurator:
    def execute(self, plan: ThinClientLauncherPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for rel, content, mode in plan.files:
            target = plan.rootfs / str(rel).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise ThinClientLauncherError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temp = target.with_name(target.name + ".tmp")
            temp.write_text(content, encoding="utf-8")
            temp.chmod(mode)
            temp.replace(target)
            written.append(target)
        return tuple(written)
