"""Virtual-terminal lockdown and authenticated administrative TTY for phase 5.4."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class TtyControlError(RuntimeError):
    """Raised when the TTY control policy is invalid or unsafe."""


_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_SHORTCUT_RE = re.compile(r"^Ctrl\+Alt\+F(?:[1-9]|1[0-2])$")


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise TtyControlError(f"Ruta insegura: {name}")
    return path


def load_tty_control_profile(path: Path) -> dict[str, Any]:
    """Load and strictly validate the phase 5.4 TTY policy."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TtyControlError(f"No s'ha pogut carregar la política TTY: {exc}") from exc
    required = {"schema_version", "policy", "virtual_terminals", "administration", "switching", "files"}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or set(raw) != required:
        raise TtyControlError("Esquema de control TTY invàlid")

    policy = raw["policy"]
    if not isinstance(policy, dict) or set(policy) != {"identifier", "default_decision", "enforcement_mode", "kiosk_user"}:
        raise TtyControlError("Política TTY incompleta")
    if policy["default_decision"] != "deny" or policy["enforcement_mode"] != "enforce":
        raise TtyControlError("El control TTY ha de denegar per defecte i aplicar-se")
    if policy["kiosk_user"] != "xaac-kiosk" or not isinstance(policy["identifier"], str) or not policy["identifier"].strip():
        raise TtyControlError("Identitat de política TTY invàlida")

    terminals = raw["virtual_terminals"]
    expected_vts = {"minimum", "maximum", "administrative_tty", "disabled_user_ttys", "reserve_administrative_tty", "automatic_vts"}
    if not isinstance(terminals, dict) or set(terminals) != expected_vts:
        raise TtyControlError("Definició de terminals virtuals incompleta")
    minimum, maximum, admin = terminals["minimum"], terminals["maximum"], terminals["administrative_tty"]
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (minimum, maximum, admin)):
        raise TtyControlError("Els números de TTY han de ser enters")
    if minimum != 1 or maximum != 12 or not minimum <= admin <= maximum:
        raise TtyControlError("Rang de TTY invàlid")
    disabled = terminals["disabled_user_ttys"]
    if not isinstance(disabled, list) or not disabled or not all(isinstance(value, int) and not isinstance(value, bool) for value in disabled):
        raise TtyControlError("Llista de TTY d'usuari invàlida")
    if len(disabled) != len(set(disabled)) or admin in disabled:
        raise TtyControlError("El TTY administratiu no pot estar deshabilitat")
    if set(disabled) != set(range(minimum, maximum + 1)) - {admin}:
        raise TtyControlError("Tots els TTY no administratius han d'estar deshabilitats")
    if terminals["reserve_administrative_tty"] is not True or terminals["automatic_vts"] != 0:
        raise TtyControlError("El TTY administratiu ha d'estar reservat i els VT automàtics deshabilitats")

    administration = raw["administration"]
    expected_admin = {"allowed_user", "authentication_required", "clear_screen", "issue_banner", "securetty_only"}
    if not isinstance(administration, dict) or set(administration) != expected_admin:
        raise TtyControlError("Política d'administració TTY incompleta")
    if not isinstance(administration["allowed_user"], str) or not _USER_RE.fullmatch(administration["allowed_user"]):
        raise TtyControlError("Usuari administrador invàlid")
    if administration["allowed_user"] != "xaac-admin":
        raise TtyControlError("Només xaac-admin pot usar el TTY administratiu")
    if administration["authentication_required"] is not True or administration["securetty_only"] is not True:
        raise TtyControlError("L'autenticació segura del TTY administratiu és obligatòria")
    if not isinstance(administration["clear_screen"], bool) or not isinstance(administration["issue_banner"], bool):
        raise TtyControlError("Opcions visuals del TTY invàlides")

    switching = raw["switching"]
    if not isinstance(switching, dict) or set(switching) != {"kiosk_switching_allowed", "reserved_shortcut", "require_capability"}:
        raise TtyControlError("Política de canvi de TTY incompleta")
    if switching["kiosk_switching_allowed"] is not False or switching["require_capability"] != "CAP_SYS_TTY_CONFIG":
        raise TtyControlError("El canvi de TTY del quiosc ha d'estar bloquejat")
    shortcut = switching["reserved_shortcut"]
    if not isinstance(shortcut, str) or not _SHORTCUT_RE.fullmatch(shortcut) or int(shortcut.removeprefix("Ctrl+Alt+F")) != admin:
        raise TtyControlError("La drecera reservada no correspon al TTY administratiu")

    files = raw["files"]
    if not isinstance(files, dict) or set(files) != {"logind", "getty_override", "securetty", "policy"}:
        raise TtyControlError("Destinacions de fitxers TTY invàlides")
    for name, value in files.items():
        _safe_absolute(value, name)
    return raw


@dataclass(frozen=True, slots=True)
class TtyControlPlan:
    rootfs: Path
    administrative_tty: int
    disabled_ttys: tuple[int, ...]
    allowed_user: str
    files: tuple[tuple[PurePosixPath, str, int], ...]
    mask_units: tuple[str, ...]
    enable_unit: str

    def to_manifest(self) -> dict[str, object]:
        return {
            "administrative_tty": self.administrative_tty,
            "disabled_ttys": list(self.disabled_ttys),
            "allowed_user": self.allowed_user,
            "files": [str(path) for path, _, _ in self.files],
            "mask_units": list(self.mask_units),
            "enable_unit": self.enable_unit,
            "enforcement": "enforce",
        }


def create_tty_control_plan(rootfs: Path, profile_path: Path) -> TtyControlPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise TtyControlError(f"Rootfs insegur: {root}")
    profile = load_tty_control_profile(profile_path)
    terminals = profile["virtual_terminals"]
    admin = profile["administration"]
    tty = terminals["administrative_tty"]
    logind = "[Login]\nNAutoVTs=0\nReserveVT=%d\nKillUserProcesses=yes\n" % tty
    getty = (
        "[Service]\n"
        "ExecStart=\n"
        "ExecStart=-/sbin/agetty --noreset --noclear --noissue - linux\n"
        "TTYReset=yes\nTTYVHangup=yes\nTTYVTDisallocate=yes\n"
    )
    securetty = f"tty{tty}\n"
    effective = {key: value for key, value in profile.items() if key != "files"}
    destinations = profile["files"]
    files = (
        (_safe_absolute(destinations["logind"], "logind"), logind, 0o644),
        (_safe_absolute(destinations["getty_override"], "getty_override"), getty, 0o644),
        (_safe_absolute(destinations["securetty"], "securetty"), securetty, 0o600),
        (_safe_absolute(destinations["policy"], "policy"), json.dumps(effective, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640),
    )
    disabled = tuple(terminals["disabled_user_ttys"])
    masks = tuple(unit for number in disabled for unit in (f"getty@tty{number}.service", f"autovt@tty{number}.service"))
    return TtyControlPlan(root, tty, disabled, admin["allowed_user"], files, masks, f"getty@tty{tty}.service")


class TtyControlConfigurator:
    """Write TTY policy files and systemd masks atomically and idempotently."""

    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise TtyControlError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        temporary.replace(path)

    @staticmethod
    def _link(path: Path, target: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            if path.is_symlink() and os.readlink(path) == target:
                return
            if path.is_dir() and not path.is_symlink():
                raise TtyControlError(f"No es reemplaçarà un directori: {path}")
            path.unlink()
        path.symlink_to(target)

    def execute(self, plan: TtyControlPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for relative, content, mode in plan.files:
            target = plan.rootfs / str(relative).lstrip("/")
            self._write(target, content, mode)
            written.append(target)
        for unit in plan.mask_units:
            target = plan.rootfs / "etc/systemd/system" / unit
            self._link(target, "/dev/null")
            written.append(target)
        wants = plan.rootfs / "etc/systemd/system/getty.target.wants" / plan.enable_unit
        self._link(wants, "/lib/systemd/system/getty@.service")
        written.append(wants)
        return tuple(written)
