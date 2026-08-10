"""Minimal Wayland/X11, Mesa, GTK 4 and input stack for the kiosk session."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class GraphicalStackError(RuntimeError):
    """Raised when the graphical stack profile or target is unsafe."""


@dataclass(frozen=True, slots=True)
class GraphicalStackInventory:
    session_type: str | None
    display: str | None
    wayland_display: str | None
    gtk_major: int | None
    renderer: str | None
    width: int | None
    height: int | None
    keyboard_present: bool
    pointer_present: bool


@dataclass(frozen=True, slots=True)
class StackCheck:
    name: str
    status: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "expected": self.expected, "actual": self.actual}


@dataclass(frozen=True, slots=True)
class GraphicalStackReport:
    profile: str
    compatible: bool
    checks: tuple[StackCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {"profile": self.profile, "compatible": self.compatible, "checks": [c.to_dict() for c in self.checks]}


def load_graphical_stack_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GraphicalStackError(f"No s'ha pogut carregar el perfil de pila gràfica: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise GraphicalStackError("Perfil de pila gràfica invàlid o esquema no suportat")
    for key in ("profile", "backend", "packages", "environment", "fonts", "validation"):
        if key not in raw:
            raise GraphicalStackError(f"Falta la secció obligatòria: {key}")
    backend = raw["backend"]
    if not isinstance(backend, dict) or backend.get("primary") != "wayland" or backend.get("fallback") != "x11":
        raise GraphicalStackError("Wayland ha de ser el backend principal i X11 l'alternativa")
    required = raw["packages"].get("required") if isinstance(raw["packages"], dict) else None
    if not isinstance(required, list) or not required or not all(isinstance(p, str) and re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", p) for p in required):
        raise GraphicalStackError("La llista de paquets requerits és invàlida")
    variables = raw["environment"].get("variables") if isinstance(raw["environment"], dict) else None
    if not isinstance(variables, dict) or variables.get("GDK_BACKEND") != "wayland,x11":
        raise GraphicalStackError("GDK_BACKEND ha de prioritzar wayland i permetre x11")
    fonts = raw["fonts"]
    if not isinstance(fonts, dict) or fonts.get("default_family") != "Roboto":
        raise GraphicalStackError("Roboto ha de ser la família tipogràfica per defecte")
    size = fonts.get("default_size")
    if not isinstance(size, int) or size <= 0:
        raise GraphicalStackError("La mida de font GTK és invàlida")
    for key in ("sans_fallbacks", "serif_fallbacks", "monospace_fallbacks"):
        values = fonts.get(key)
        if not isinstance(values, list) or not values or not all(isinstance(value, str) and value.strip() for value in values):
            raise GraphicalStackError(f"La llista tipogràfica {key} és invàlida")
    for key in ("fontconfig_file", "gtk3_settings_file", "gtk4_settings_file"):
        value = PurePosixPath(str(fonts.get(key, "")))
        if not value.is_absolute() or ".." in value.parts:
            raise GraphicalStackError(f"Ruta tipogràfica insegura: {key}")
    return raw


def compare_graphical_stack(inventory: GraphicalStackInventory, profile: dict[str, Any]) -> GraphicalStackReport:
    validation = profile["validation"]
    backend = profile["backend"]
    checks: list[StackCheck] = []

    def add(name: str, ok: bool, expected: object, actual: object) -> None:
        checks.append(StackCheck(name, "pass" if ok else "fail", str(expected), str(actual)))

    allowed = (backend["primary"], backend["fallback"]) if backend.get("allow_fallback", False) else (backend["primary"],)
    add("backend", inventory.session_type in allowed, allowed, inventory.session_type)
    add("display", bool(inventory.wayland_display or inventory.display), "active graphical display", inventory.wayland_display or inventory.display)
    add("gtk", inventory.gtk_major == int(validation["gtk_major"]), validation["gtk_major"], inventory.gtk_major)
    add("renderer", bool(inventory.renderer), "Mesa/OpenGL renderer", inventory.renderer)
    minimum_width = int(validation["minimum_width"])
    minimum_height = int(validation["minimum_height"])
    resolution_ok = inventory.width is not None and inventory.height is not None and inventory.width >= minimum_width and inventory.height >= minimum_height
    add("resolution", resolution_ok, f">={minimum_width}x{minimum_height}", f"{inventory.width}x{inventory.height}")
    add("keyboard", inventory.keyboard_present or not validation.get("require_keyboard", True), True, inventory.keyboard_present)
    add("pointer", inventory.pointer_present or not validation.get("require_pointer", True), True, inventory.pointer_present)
    return GraphicalStackReport(str(profile["profile"]), all(c.status == "pass" for c in checks), tuple(checks))


@dataclass(frozen=True, slots=True)
class GraphicalStackPlan:
    rootfs: Path
    packages: tuple[str, ...]
    forbidden_packages: tuple[str, ...]
    files: tuple[tuple[PurePosixPath, str, int], ...]

    def to_manifest(self) -> dict[str, object]:
        return {"packages": list(self.packages), "forbidden_packages": list(self.forbidden_packages), "files": [str(p) for p, _, _ in self.files]}


def create_graphical_stack_plan(rootfs: Path, profile_path: Path) -> GraphicalStackPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise GraphicalStackError(f"Rootfs insegur: {root}")
    profile = load_graphical_stack_profile(profile_path)
    environment = profile["environment"]
    env_path = PurePosixPath(str(environment["file"]))
    if not env_path.is_absolute() or ".." in env_path.parts:
        raise GraphicalStackError("Ruta del fitxer d'entorn insegura")
    variables = environment["variables"]
    lines = ["# Generated by XAAC Thin Client OS - Phase 4.1"]
    for key, value in sorted(variables.items()):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(key)) or "\n" in str(value):
            raise GraphicalStackError("Variable d'entorn invàlida")
        lines.append(f'{key}="{str(value)}"')
    content = "\n".join(lines) + "\n"

    fonts = profile["fonts"]
    fontconfig_path = PurePosixPath(str(fonts["fontconfig_file"]))
    gtk3_path = PurePosixPath(str(fonts["gtk3_settings_file"]))
    gtk4_path = PurePosixPath(str(fonts["gtk4_settings_file"]))
    default_family = str(fonts["default_family"])
    sans_families = [default_family, *fonts["sans_fallbacks"]]
    serif_families = [default_family, *fonts["serif_fallbacks"]]
    monospace_families = [*fonts["monospace_fallbacks"]]

    def alias_xml(generic: str, families: list[str]) -> list[str]:
        result = ["  <alias>", f"    <family>{generic}</family>", "    <prefer>"]
        result.extend(f"      <family>{family}</family>" for family in families)
        result.extend(["    </prefer>", "  </alias>"])
        return result

    fontconfig_lines = [
        '<?xml version="1.0"?>',
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">',
        '<fontconfig>',
    ]
    fontconfig_lines.extend(alias_xml("sans-serif", sans_families))
    fontconfig_lines.extend(alias_xml("serif", serif_families))
    fontconfig_lines.extend(alias_xml("monospace", monospace_families))
    fontconfig_lines.append("</fontconfig>")
    fontconfig_content = "\n".join(fontconfig_lines) + "\n"

    gtk_settings_content = (
        "[Settings]\n"
        f"gtk-font-name={default_family} {int(fonts['default_size'])}\n"
        "gtk-icon-theme-name=ZorinBlue-Light\n"
    )
    files = (
        (env_path, content, 0o644),
        (fontconfig_path, fontconfig_content, 0o644),
        (gtk3_path, gtk_settings_content, 0o644),
        (gtk4_path, gtk_settings_content, 0o644),
    )
    packages = tuple(dict.fromkeys(profile["packages"]["required"]))
    forbidden = tuple(dict.fromkeys(profile["packages"].get("forbidden", [])))
    return GraphicalStackPlan(root, packages, forbidden, files)


class GraphicalStackConfigurator:
    def execute(self, plan: GraphicalStackPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for relative, content, mode in plan.files:
            target = plan.rootfs / str(relative).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise GraphicalStackError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temporary = target.with_name(target.name + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(mode)
            temporary.replace(target)
            written.append(target)
        return tuple(written)
