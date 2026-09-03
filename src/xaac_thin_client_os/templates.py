"""Safe deterministic template rendering for image configuration files."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TemplateError(RuntimeError):
    """Base error raised by the template subsystem."""


class TemplateVariableError(TemplateError):
    """Raised when a required template variable is unavailable."""


class TemplatePathError(TemplateError):
    """Raised when a template path could escape an approved directory."""


_VARIABLE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*}}")


@dataclass(frozen=True, slots=True)
class RenderedTemplate:
    """Metadata for one rendered template file."""

    source: Path
    destination: Path
    changed: bool
    variables: tuple[str, ...]


def _safe_relative(path: Path, *, label: str) -> Path:
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise TemplatePathError(f"{label} ha de ser una ruta relativa segura")
    return path


def _resolve_variable(context: Mapping[str, Any], name: str) -> object:
    value: object = context
    for component in name.split("."):
        if not isinstance(value, Mapping) or component not in value:
            raise TemplateVariableError(f"Variable de plantilla no definida: {name}")
        value = value[component]
    if isinstance(value, (dict, list, tuple, set)):
        raise TemplateVariableError(f"La variable de plantilla no és escalar: {name}")
    if value is None:
        raise TemplateVariableError(f"La variable de plantilla no té valor: {name}")
    return value


def render_text(template: str, context: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    """Render scalar ``{{ dotted.variable }}`` expressions in text."""
    variables: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        variables.append(name)
        value = _resolve_variable(context, name)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    rendered = _VARIABLE.sub(replace, template)
    if "{{" in rendered or "}}" in rendered:
        raise TemplateError("Expressió de plantilla no vàlida o no suportada")
    return rendered, tuple(dict.fromkeys(variables))


class TemplateRenderer:
    """Render a trusted template tree into an isolated destination tree."""

    def __init__(self, template_root: Path, destination_root: Path) -> None:
        self.template_root = template_root.resolve()
        self.destination_root = destination_root.resolve()

    def _source(self, relative: Path) -> Path:
        safe = _safe_relative(relative, label="La plantilla")
        source = (self.template_root / safe).resolve()
        if not source.is_relative_to(self.template_root):
            raise TemplatePathError("La plantilla ix del directori autoritzat")
        if not source.is_file():
            raise TemplateError(f"No existeix la plantilla: {safe}")
        return source

    def _destination(self, relative: Path) -> Path:
        safe = _safe_relative(relative, label="La destinació")
        destination = (self.destination_root / safe).resolve()
        if not destination.is_relative_to(self.destination_root):
            raise TemplatePathError("La destinació ix del directori autoritzat")
        return destination

    def render_file(
        self,
        template: Path,
        destination: Path,
        context: Mapping[str, Any],
    ) -> RenderedTemplate:
        """Render one UTF-8 template atomically and idempotently."""
        source = self._source(template)
        target = self._destination(destination)
        rendered, variables = render_text(source.read_text(encoding="utf-8"), context)
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = target.read_text(encoding="utf-8") if target.is_file() else None
        changed = previous != rendered
        if changed:
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_text(rendered, encoding="utf-8")
            temporary.replace(target)
        return RenderedTemplate(source, target, changed, variables)

    def render_tree(self, context: Mapping[str, Any]) -> tuple[RenderedTemplate, ...]:
        """Render every ``*.tpl`` file, removing only the final suffix."""
        if not self.template_root.is_dir():
            raise TemplateError(f"No existeix el directori de plantilles: {self.template_root}")
        results: list[RenderedTemplate] = []
        for source in sorted(self.template_root.rglob("*.tpl")):
            relative = source.relative_to(self.template_root)
            destination = relative.with_suffix("")
            results.append(self.render_file(relative, destination, context))
        return tuple(results)
