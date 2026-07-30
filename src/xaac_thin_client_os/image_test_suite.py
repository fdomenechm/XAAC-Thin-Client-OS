"""Deterministic image-test assets for phase 12.6."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class ImageTestSuiteError(RuntimeError):
    """Raised when the image test policy is incomplete or unsafe."""

def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith('/'):
        raise ImageTestSuiteError(f"Ruta relativa invàlida en {field}")
    if any(part in {'.', '..'} for part in PurePosixPath(value).parts):
        raise ImageTestSuiteError(f"Ruta insegura en {field}")
    return value

def load_image_test_suite(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        raise ImageTestSuiteError(f"No s'ha pogut carregar la política de proves d'imatge: {exc}") from exc
    if not isinstance(raw, dict) or raw.get('schema_version') != 1:
        raise ImageTestSuiteError("Política de proves d'imatge invàlida")
    if raw.get('product') != 'XAAC Thin Client OS' or raw.get('architecture') != 'amd64':
        raise ImageTestSuiteError("Producte o arquitectura no suportats")
    if raw.get('hardware_profile') != 'wyse3040':
        raise ImageTestSuiteError("Perfil de maquinari no suportat")
    categories = raw.get('categories')
    required = ['boot', 'services', 'partitions', 'users', 'packages', 'security', 'update', 'recovery']
    if not isinstance(categories, dict) or list(categories) != required:
        raise ImageTestSuiteError("Categories de validació incompletes o desordenades")
    for name in required:
        item = categories[name]
        if not isinstance(item, dict) or item.get('enabled') is not True or not isinstance(item.get('checks'), list) or not item['checks'] or any(not isinstance(check, str) or not check for check in item['checks']):
            raise ImageTestSuiteError(f"Categoria obligatòria invàlida: {name}")
    execution = raw.get('execution')
    if not isinstance(execution, dict) or execution.get('fail_fast') is not False:
        raise ImageTestSuiteError("La suite ha d'executar totes les comprovacions")
    if execution.get('require_clean_shutdown') is not True or execution.get('collect_journal') is not True:
        raise ImageTestSuiteError("Controls d'execució obligatoris absents")
    if not isinstance(execution.get('timeout_seconds'), int) or not 60 <= execution['timeout_seconds'] <= 3600:
        raise ImageTestSuiteError("Timeout de proves invàlid")
    outputs = raw.get('outputs')
    expected = {'manifest', 'runner', 'report_schema'}
    if not isinstance(outputs, dict) or set(outputs) != expected:
        raise ImageTestSuiteError("outputs de proves incomplets")
    raw['outputs'] = {key: _safe_relative(value, f'outputs.{key}') for key, value in outputs.items()}
    return raw

@dataclass(frozen=True, slots=True)
class ImageTestSuitePlan:
    project_root: Path
    profile: dict[str, Any]
    def output(self, key: str) -> Path:
        return self.project_root / self.profile['outputs'][key]
    def manifest(self) -> dict[str, object]:
        return {
            'schema_version': 1,
            'profile_id': self.profile['profile_id'],
            'product': 'XAAC Thin Client OS',
            'architecture': 'amd64',
            'hardware_profile': 'wyse3040',
            'categories': list(self.profile['categories']),
            'check_count': sum(len(v['checks']) for v in self.profile['categories'].values()),
            'timeout_seconds': self.profile['execution']['timeout_seconds'],
            'fail_fast': False,
        }

def create_image_test_suite_plan(project_root: Path, profile_path: Path) -> ImageTestSuitePlan:
    root = project_root.resolve()
    if root == Path('/'):
        raise ImageTestSuiteError(f"Arrel de projecte insegura: {root}")
    return ImageTestSuitePlan(root, load_image_test_suite(profile_path))

class ImageTestSuiteBuilder:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise ImageTestSuiteError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    def prepare(self, plan: ImageTestSuitePlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        keys = ('manifest', 'runner', 'report_schema')
        targets = tuple(plan.output(key) for key in keys)
        if dry_run:
            return targets
        self._write(plan.output('manifest'), json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + '\n', 0o644)
        checks = []
        for category, spec in plan.profile['categories'].items():
            for command in spec['checks']:
                checks.append((category, command))
        lines = ['#!/bin/sh', 'set -u', 'REPORT=${1:-/var/log/xaac/image-tests.json}', 'TMP=$(mktemp)', "trap 'rm -f \"$TMP\"' EXIT", 'failed=0', "printf '%s\\n' '[' > \"$TMP\"", 'first=1']
        for category, command in checks:
            escaped = command.replace('\\', '\\\\').replace('"', '\\"')
            lines += [f'if sh -c "{escaped}"; then status=passed; else status=failed; failed=$((failed+1)); fi', '[ "$first" -eq 1 ] || printf ",\\n" >> "$TMP"', 'first=0', f'printf \'  {{"category":"{category}","command":"%s","status":"%s"}}\' "{escaped}" "$status" >> "$TMP"']
        lines += ["printf '\\n]\\n' >> \"$TMP\"", 'install -d -m 0750 "$(dirname "$REPORT")"', 'install -m 0640 "$TMP" "$REPORT"', '[ "$failed" -eq 0 ]']
        self._write(plan.output('runner'), '\n'.join(lines) + '\n', 0o750)
        schema = {'$schema':'https://json-schema.org/draft/2020-12/schema','type':'array','items':{'type':'object','required':['category','command','status'],'properties':{'category':{'enum':list(plan.profile['categories'])},'command':{'type':'string','minLength':1},'status':{'enum':['passed','failed']},},'additionalProperties':False}}
        self._write(plan.output('report_schema'), json.dumps(schema, indent=2, sort_keys=True) + '\n', 0o644)
        return targets
