"""Terminal, launcher, URI and PATH lockdown for the XAAC kiosk session."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class TerminalLockdownError(RuntimeError):
    """Raised when phase 5.3 terminal-lockdown data is invalid or unsafe."""


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise TerminalLockdownError(f"Ruta insegura: {name}")
    return path


def _string_list(value: object, name: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise TerminalLockdownError(f"Llista invàlida: {name}")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise TerminalLockdownError(f"Valor invàlid: {name}")
    if len(value) != len(set(value)):
        raise TerminalLockdownError(f"Valors duplicats: {name}")
    return value


def load_terminal_lockdown_profile(path: Path) -> dict[str, Any]:
    """Load and strictly validate the phase 5.3 policy."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TerminalLockdownError(f"No s'ha pogut carregar la política: {exc}") from exc
    required = {"schema_version", "policy", "terminal_emulators", "command_execution", "uri", "path", "files"}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or set(raw) != required:
        raise TerminalLockdownError("Esquema de bloqueig de terminals invàlid")
    policy = raw["policy"]
    if not isinstance(policy, dict) or policy.get("default_decision") != "deny":
        raise TerminalLockdownError("La política ha de denegar per defecte")
    if policy.get("enforcement_mode") != "enforce" or policy.get("kiosk_user") != "xaac-kiosk":
        raise TerminalLockdownError("La política no és aplicable al quiosc")
    if not isinstance(policy.get("identifier"), str) or not policy["identifier"].strip():
        raise TerminalLockdownError("Identificador de política invàlid")

    terminals = raw["terminal_emulators"]
    if not isinstance(terminals, dict) or set(terminals) != {"forbidden_packages", "forbidden_executables"}:
        raise TerminalLockdownError("Definició d'emuladors incompleta")
    _string_list(terminals["forbidden_packages"], "terminal_emulators.forbidden_packages")
    _string_list(terminals["forbidden_executables"], "terminal_emulators.forbidden_executables")

    commands = raw["command_execution"]
    expected_commands = {"allowed_executables", "forbidden_shells", "forbid_interpreters_from_launchers", "forbid_user_desktop_files"}
    if not isinstance(commands, dict) or set(commands) != expected_commands:
        raise TerminalLockdownError("Política d'execució incompleta")
    allowed = _string_list(commands["allowed_executables"], "command_execution.allowed_executables")
    forbidden_shells = _string_list(commands["forbidden_shells"], "command_execution.forbidden_shells")
    if not all(PurePosixPath(item).is_absolute() for item in allowed + forbidden_shells):
        raise TerminalLockdownError("Els executables han d'usar rutes absolutes")
    if commands["forbid_interpreters_from_launchers"] is not True or commands["forbid_user_desktop_files"] is not True:
        raise TerminalLockdownError("Els llançadors arbitraris han d'estar prohibits")

    uri = raw["uri"]
    if not isinstance(uri, dict) or set(uri) != {"allowed_schemes", "forbidden_schemes", "disable_generic_openers"}:
        raise TerminalLockdownError("Política d'URI incompleta")
    allowed_schemes = _string_list(uri["allowed_schemes"], "uri.allowed_schemes")
    forbidden_schemes = _string_list(uri["forbidden_schemes"], "uri.forbidden_schemes")
    if set(allowed_schemes) & set(forbidden_schemes):
        raise TerminalLockdownError("Un esquema URI no pot estar permés i prohibit")
    if uri["disable_generic_openers"] is not True:
        raise TerminalLockdownError("Els obridors URI genèrics han d'estar deshabilitats")

    path_policy = raw["path"]
    expected_path = {"value", "require_absolute_entries", "forbid_empty_entries", "forbid_writable_entries", "forbidden_entries"}
    if not isinstance(path_policy, dict) or set(path_policy) != expected_path:
        raise TerminalLockdownError("Política PATH incompleta")
    if path_policy["require_absolute_entries"] is not True or path_policy["forbid_empty_entries"] is not True or path_policy["forbid_writable_entries"] is not True:
        raise TerminalLockdownError("La validació segura del PATH és obligatòria")
    value = path_policy["value"]
    if not isinstance(value, str) or not value or "::" in value or value.startswith(":") or value.endswith(":"):
        raise TerminalLockdownError("PATH invàlid")
    entries = value.split(":")
    if not all(PurePosixPath(entry).is_absolute() for entry in entries):
        raise TerminalLockdownError("El PATH només pot contindre rutes absolutes")
    forbidden_entries = _string_list(path_policy["forbidden_entries"], "path.forbidden_entries")
    if set(entries) & set(forbidden_entries):
        raise TerminalLockdownError("El PATH conté una ruta prohibida")

    files = raw["files"]
    if not isinstance(files, dict) or set(files) != {"environment", "mimeapps", "policy"}:
        raise TerminalLockdownError("Destinacions de fitxers invàlides")
    for name, value in files.items():
        _safe_absolute(value, name)
    return raw


@dataclass(frozen=True, slots=True)
class TerminalLockdownPlan:
    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]
    forbidden_packages: tuple[str, ...]
    forbidden_executables: tuple[str, ...]
    path_entries: tuple[str, ...]

    def to_manifest(self) -> dict[str, object]:
        return {
            "files": [str(path) for path, _, _ in self.files],
            "forbidden_packages": list(self.forbidden_packages),
            "forbidden_executables": list(self.forbidden_executables),
            "path_entries": list(self.path_entries),
            "enforcement": "enforce",
        }


def create_terminal_lockdown_plan(rootfs: Path, profile_path: Path) -> TerminalLockdownPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise TerminalLockdownError(f"Rootfs insegur: {root}")
    profile = load_terminal_lockdown_profile(profile_path)
    path_value = profile["path"]["value"]
    environment = (
        "# Generated by XAAC Thin Client OS; do not edit.\n"
        f"PATH={path_value}\n"
        "BROWSER=/usr/bin/false\n"
        "TERMINAL=/usr/bin/false\n"
        "GIO_USE_VFS=local\n"
    )
    forbidden = profile["uri"]["forbidden_schemes"]
    mime_lines = ["[Default Applications]"]
    mime_lines.extend(f"x-scheme-handler/{scheme}=xaac-disabled.desktop;" for scheme in forbidden)
    mime_lines.extend(["", "[Added Associations]"])
    mime_lines.extend(f"x-scheme-handler/{scheme}=xaac-disabled.desktop;" for scheme in forbidden)
    mimeapps = "\n".join(mime_lines) + "\n"
    effective = {key: value for key, value in profile.items() if key != "files"}
    files = profile["files"]
    generated = (
        (_safe_absolute(files["environment"], "environment"), environment, 0o640),
        (_safe_absolute(files["mimeapps"], "mimeapps"), mimeapps, 0o640),
        (_safe_absolute(files["policy"], "policy"), json.dumps(effective, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640),
    )
    terminals = profile["terminal_emulators"]
    return TerminalLockdownPlan(
        rootfs=root,
        files=generated,
        forbidden_packages=tuple(terminals["forbidden_packages"]),
        forbidden_executables=tuple(terminals["forbidden_executables"]),
        path_entries=tuple(path_value.split(":")),
    )


class TerminalLockdownConfigurator:
    """Atomically write the kiosk terminal-lockdown configuration."""

    def execute(self, plan: TerminalLockdownPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for relative, content, mode in plan.files:
            target = plan.rootfs / str(relative).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise TerminalLockdownError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temporary = target.with_name(f"{target.name}.tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(mode)
            temporary.replace(target)
            written.append(target)
        return tuple(written)
