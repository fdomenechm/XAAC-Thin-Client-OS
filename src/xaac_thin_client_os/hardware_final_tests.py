"""Deterministic final hardware-test assets for phase 12.7."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class HardwareFinalTestsError(RuntimeError):
    """Raised when the final hardware-test policy is incomplete or unsafe."""


def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise HardwareFinalTestsError(f"Ruta relativa invàlida en {field}")
    if any(part in {".", ".."} for part in PurePosixPath(value).parts):
        raise HardwareFinalTestsError(f"Ruta insegura en {field}")
    return value


def load_hardware_final_tests(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise HardwareFinalTestsError(f"No s'ha pogut carregar la política de proves de maquinari: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise HardwareFinalTestsError("Política de proves de maquinari invàlida")
    if raw.get("product") != "XAAC Thin Client OS" or raw.get("hardware_profile") != "wyse3040":
        raise HardwareFinalTestsError("Producte o perfil de maquinari no suportats")
    if raw.get("require_real_hardware") is not True:
        raise HardwareFinalTestsError("Les proves finals exigeixen maquinari real")
    categories = raw.get("categories")
    required = ["installation", "continuous_use", "rdp", "peripherals", "update", "factory_reset", "recovery"]
    if not isinstance(categories, dict) or list(categories) != required:
        raise HardwareFinalTestsError("Categories de maquinari incompletes o desordenades")
    for name in required:
        item = categories[name]
        if not isinstance(item, dict) or item.get("enabled") is not True:
            raise HardwareFinalTestsError(f"Categoria obligatòria invàlida: {name}")
        checks = item.get("checks")
        if not isinstance(checks, list) or not checks or any(not isinstance(check, str) or not check for check in checks):
            raise HardwareFinalTestsError(f"Comprovacions invàlides: {name}")
    execution = raw.get("execution")
    if not isinstance(execution, dict) or execution.get("fail_fast") is not False:
        raise HardwareFinalTestsError("La suite ha d'executar totes les comprovacions")
    if execution.get("collect_inventory") is not True or execution.get("collect_journal") is not True:
        raise HardwareFinalTestsError("Recollida d'evidències obligatòria absent")
    duration = execution.get("continuous_use_hours")
    if not isinstance(duration, int) or not 1 <= duration <= 168:
        raise HardwareFinalTestsError("Duració de prova contínua invàlida")
    outputs = raw.get("outputs")
    expected = {"manifest", "runner", "checklist", "report_schema"}
    if not isinstance(outputs, dict) or set(outputs) != expected:
        raise HardwareFinalTestsError("outputs de proves de maquinari incomplets")
    raw["outputs"] = {key: _safe_relative(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class HardwareFinalTestsPlan:
    project_root: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.project_root / self.profile["outputs"][key]

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "profile_id": self.profile["profile_id"],
            "product": "XAAC Thin Client OS",
            "hardware_profile": "wyse3040",
            "require_real_hardware": True,
            "categories": list(self.profile["categories"]),
            "check_count": sum(len(item["checks"]) for item in self.profile["categories"].values()),
            "continuous_use_hours": self.profile["execution"]["continuous_use_hours"],
            "fail_fast": False,
        }


def create_hardware_final_tests_plan(project_root: Path, profile_path: Path) -> HardwareFinalTestsPlan:
    root = project_root.resolve()
    if root == Path("/"):
        raise HardwareFinalTestsError(f"Arrel de projecte insegura: {root}")
    return HardwareFinalTestsPlan(root, load_hardware_final_tests(profile_path))


class HardwareFinalTestsBuilder:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise HardwareFinalTestsError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def prepare(self, plan: HardwareFinalTestsPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        keys = ("manifest", "runner", "checklist", "report_schema")
        targets = tuple(plan.output(key) for key in keys)
        if dry_run:
            return targets
        self._write(plan.output("manifest"), json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o644)
        categories = plan.profile["categories"]
        lines = [
            "#!/bin/sh", "set -u", "REPORT=${1:-/var/log/xaac/hardware-final-tests.json}",
            "EVIDENCE=${2:-/var/log/xaac/hardware-final-evidence}", "install -d -m 0750 \"$EVIDENCE\"", "failed=0",
            "command -v dmidecode >/dev/null 2>&1 && dmidecode > \"$EVIDENCE/dmidecode.txt\" 2>&1 || true",
            "lspci -nnk > \"$EVIDENCE/lspci.txt\" 2>&1 || true", "lsusb -v > \"$EVIDENCE/lsusb.txt\" 2>&1 || true",
            "journalctl -b --no-pager > \"$EVIDENCE/journal.txt\" 2>&1 || true", "TMP=$(mktemp)", "trap 'rm -f \"$TMP\"' EXIT",
            "printf '%s\\n' '[' > \"$TMP\"", "first=1",
        ]
        for category, spec in categories.items():
            for command in spec["checks"]:
                escaped = command.replace("\\", "\\\\").replace('"', '\\"')
                lines += [
                    f'if sh -c "{escaped}"; then status=passed; else status=failed; failed=$((failed+1)); fi',
                    '[ "$first" -eq 1 ] || printf ",\\n" >> "$TMP"', "first=0",
                    f'printf \'  {{"category":"{category}","command":"%s","status":"%s"}}\' "{escaped}" "$status" >> "$TMP"',
                ]
        lines += ["printf '\\n]\\n' >> \"$TMP\"", "install -d -m 0750 \"$(dirname \"$REPORT\")\"", "install -m 0640 \"$TMP\" \"$REPORT\"", '[ "$failed" -eq 0 ]']
        self._write(plan.output("runner"), "\n".join(lines) + "\n", 0o750)
        checklist_lines = ["# Proves finals de maquinari — Dell Wyse 3040", "", "Registreu operador, número de sèrie, data, versió i resultat de cada comprovació.", ""]
        for category, spec in categories.items():
            checklist_lines += [f"## {category}"] + [f"- [ ] {check}" for check in spec["checks"]] + [""]
        self._write(plan.output("checklist"), "\n".join(checklist_lines), 0o644)
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "array", "items": {"type": "object", "required": ["category", "command", "status"], "properties": {"category": {"enum": list(categories)}, "command": {"type": "string", "minLength": 1}, "status": {"enum": ["passed", "failed"]}}, "additionalProperties": False}}
        self._write(plan.output("report_schema"), json.dumps(schema, indent=2, sort_keys=True) + "\n", 0o644)
        return targets
