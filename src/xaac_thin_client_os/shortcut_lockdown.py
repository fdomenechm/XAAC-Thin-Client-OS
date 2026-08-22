"""Enforced keyboard-shortcut lockdown for the XAAC kiosk session."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class ShortcutLockdownError(RuntimeError):
    """Raised when shortcut-lockdown configuration is invalid or unsafe."""


_REQUIRED_CATEGORIES = {
    "application_switching", "window_closing", "compositor_menu",
    "command_execution", "screenshots", "system",
}


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise ShortcutLockdownError(f"Ruta insegura: {name}")
    return path


def _shortcut_list(value: object, name: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ShortcutLockdownError(f"Llista de dreceres invàlida: {name}")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ShortcutLockdownError(f"Drecera invàlida: {name}")
    if len(value) != len(set(value)):
        raise ShortcutLockdownError(f"Dreceres duplicades: {name}")
    return value


def load_shortcut_lockdown_profile(path: Path) -> dict[str, Any]:
    """Load and strictly validate the phase 5.2 shortcut policy."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ShortcutLockdownError(f"No s'ha pogut carregar la política: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ShortcutLockdownError("Esquema de dreceres invàlid")
    if set(raw) != {"schema_version", "policy", "backends", "categories", "reserved_for_later_phases", "files"}:
        raise ShortcutLockdownError("Seccions de dreceres invàlides")
    policy = raw["policy"]
    if not isinstance(policy, dict) or policy.get("default_decision") != "deny":
        raise ShortcutLockdownError("Les dreceres han de denegar-se per defecte")
    if policy.get("enforcement_mode") != "enforce" or policy.get("kiosk_user") != "xaac-kiosk":
        raise ShortcutLockdownError("La política de dreceres no és aplicable al quiosc")
    if not isinstance(policy.get("identifier"), str) or not policy["identifier"].strip():
        raise ShortcutLockdownError("Identificador de política invàlid")
    backends = raw["backends"]
    if not isinstance(backends, dict) or set(backends) != {"wayland", "x11"}:
        raise ShortcutLockdownError("Backends incomplets")
    expected = (("wayland", "compositor", "labwc"), ("x11", "window_manager", "openbox"))
    for backend, field, implementation in expected:
        item = backends.get(backend)
        if not isinstance(item, dict) or item.get(field) != implementation or item.get("disable_default_keybindings") is not True:
            raise ShortcutLockdownError(f"Backend {backend} insegur")
    categories = raw["categories"]
    if not isinstance(categories, dict) or set(categories) != _REQUIRED_CATEGORIES:
        raise ShortcutLockdownError("Categories de dreceres incompletes")
    all_shortcuts: list[str] = []
    for name in sorted(_REQUIRED_CATEGORIES):
        all_shortcuts.extend(_shortcut_list(categories[name], f"categories.{name}"))
    if len(all_shortcuts) != len(set(all_shortcuts)):
        raise ShortcutLockdownError("Una drecera apareix en més d'una categoria")
    reserved = _shortcut_list(raw["reserved_for_later_phases"], "reserved_for_later_phases")
    if set(reserved) & set(all_shortcuts):
        raise ShortcutLockdownError("Una drecera reservada no pot estar bloquejada ací")
    files = raw["files"]
    if not isinstance(files, dict) or set(files) != {"labwc_rc", "openbox_rc", "policy"}:
        raise ShortcutLockdownError("Destinacions de fitxers invàlides")
    for name, value in files.items():
        _safe_absolute(value, name)
    return raw


@dataclass(frozen=True, slots=True)
class ShortcutLockdownPlan:
    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]
    blocked_shortcuts: tuple[str, ...]

    def to_manifest(self) -> dict[str, object]:
        return {
            "files": [str(path) for path, _, _ in self.files],
            "blocked_shortcuts": list(self.blocked_shortcuts),
            "blocked_count": len(self.blocked_shortcuts),
            "enforcement": "enforce",
        }


def create_shortcut_lockdown_plan(rootfs: Path, profile_path: Path) -> ShortcutLockdownPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise ShortcutLockdownError(f"Rootfs insegur: {root}")
    profile = load_shortcut_lockdown_profile(profile_path)
    blocked = tuple(item for values in profile["categories"].values() for item in values)
    labwc = """<?xml version=\"1.0\"?>\n<labwc_config>\n  <core><decoration>server</decoration><gap>0</gap></core>\n  <placement><policy>center</policy></placement>\n  <theme>\n    <name>XAAC</name>\n    <cornerRadius>12</cornerRadius>\n    <keepBorder>yes</keepBorder>\n    <titlebar><layout>:</layout><showTitle>yes</showTitle></titlebar>\n    <font place="ActiveWindow"><name>Roboto</name><size>10</size><slant>normal</slant><weight>normal</weight></font>\n    <font place="InactiveWindow"><name>Roboto</name><size>10</size><slant>normal</slant><weight>normal</weight></font>\n  </theme>\n  <keyboard>
    <keybind key=\"A-F4\" />
  </keyboard>
  <mouse>
    <context name=\"Root\">
      <mousebind button=\"Left\" action=\"Press\" />
      <mousebind button=\"Right\" action=\"Press\" />
      <mousebind button=\"Middle\" action=\"Press\" />
    </context>
  </mouse>
  <windowRules><windowRule identifier=\"*\" serverDecoration=\"yes\"><action name=\"AutoPlace\" policy=\"center\" /></windowRule></windowRules>\n</labwc_config>\n"""
    openbox = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<openbox_config xmlns=\"http://openbox.org/3.4/rc\">\n  <applications><application class=\"*\"><decor>no</decor><fullscreen>yes</fullscreen></application></applications>\n  <keyboard />\n  <mouse><context name=\"Root\" /></mouse>\n  <desktops><number>1</number></desktops>\n</openbox_config>\n"""
    effective = {
        "schema_version": profile["schema_version"],
        "policy": profile["policy"],
        "backends": profile["backends"],
        "categories": profile["categories"],
        "reserved_for_later_phases": profile["reserved_for_later_phases"],
    }
    files = profile["files"]
    generated = (
        (_safe_absolute(files["labwc_rc"], "labwc_rc"), labwc, 0o644),
        (_safe_absolute(files["openbox_rc"], "openbox_rc"), openbox, 0o644),
        (_safe_absolute(files["policy"], "policy"), json.dumps(effective, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640),
    )
    return ShortcutLockdownPlan(root, generated, blocked)


class ShortcutLockdownConfigurator:
    """Atomically enforce the shortcut policy without following symlinks."""

    def execute(self, plan: ShortcutLockdownPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for relative, content, mode in plan.files:
            target = plan.rootfs / str(relative).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise ShortcutLockdownError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temporary = target.with_name(f"{target.name}.tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(mode)
            temporary.replace(target)
            written.append(target)
        return tuple(written)
