"""Release-candidate freeze and approval plan for phase 12.11."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class ReleaseCandidateError(RuntimeError):
    """Raised when the release-candidate configuration is incomplete or unsafe."""


REQUIRED_GATES = (
    "unit_tests",
    "image_tests",
    "hardware_tests",
    "performance_tests",
    "documentation",
    "packaging",
)
REQUIRED_ARTIFACTS = ("iso", "img", "pxe", "packages")
REQUIRED_OUTPUTS = ("manifest", "notes", "approval", "verify_script")


def _relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ReleaseCandidateError(f"Ruta relativa invàlida en {field}")
    if any(part in {".", ".."} for part in PurePosixPath(value).parts):
        raise ReleaseCandidateError(f"Ruta insegura en {field}")
    return value


def load_release_candidate_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ReleaseCandidateError(f"No s'ha pogut carregar el perfil RC: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ReleaseCandidateError("Perfil RC invàlid")
    if raw.get("product") != "XAAC Thin Client OS" or raw.get("version") != "1.0.0-rc.1":
        raise ReleaseCandidateError("Producte o versió RC invàlids")
    freeze = raw.get("freeze")
    if not isinstance(freeze, dict) or freeze.get("enabled") is not True:
        raise ReleaseCandidateError("La congelació RC és obligatòria")
    allow = freeze.get("allowed_changes")
    if not isinstance(allow, list) or not allow or any(not isinstance(v, str) or not v for v in allow):
        raise ReleaseCandidateError("Llista de canvis permesos invàlida")
    gates = raw.get("gates")
    if not isinstance(gates, dict) or tuple(gates) != REQUIRED_GATES:
        raise ReleaseCandidateError("Conjunt de portes de qualitat incomplet o desordenat")
    for name, command in gates.items():
        if not isinstance(command, str) or not command.strip():
            raise ReleaseCandidateError(f"Ordre invàlida per a {name}")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, dict) or tuple(artifacts) != REQUIRED_ARTIFACTS:
        raise ReleaseCandidateError("Conjunt d'artefactes RC incomplet o desordenat")
    raw["artifacts"] = {k: _relative(v, f"artifacts.{k}") for k, v in artifacts.items()}
    approval = raw.get("approval")
    if not isinstance(approval, dict) or approval.get("required") is not True:
        raise ReleaseCandidateError("L'aprovació RC és obligatòria")
    approvers = approval.get("roles")
    if not isinstance(approvers, list) or len(approvers) < 2 or any(not isinstance(v, str) or not v for v in approvers):
        raise ReleaseCandidateError("Rols d'aprovació insuficients")
    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or tuple(outputs) != REQUIRED_OUTPUTS:
        raise ReleaseCandidateError("Outputs RC incomplets o desordenats")
    raw["outputs"] = {k: _relative(v, f"outputs.{k}") for k, v in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class ReleaseCandidatePlan:
    root: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.root / self.profile["outputs"][key]

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "product": self.profile["product"],
            "version": self.profile["version"],
            "status": "candidate",
            "frozen": True,
            "quality_gates": list(self.profile["gates"]),
            "artifacts": self.profile["artifacts"],
            "approval_required": True,
            "approver_roles": self.profile["approval"]["roles"],
        }


def create_release_candidate_plan(root: Path, profile_path: Path) -> ReleaseCandidatePlan:
    resolved = root.resolve()
    if resolved == Path("/"):
        raise ReleaseCandidateError(f"Arrel insegura: {resolved}")
    profile = load_release_candidate_profile(profile_path)
    for name, rel in profile["artifacts"].items():
        path = resolved / rel
        if path.is_symlink():
            raise ReleaseCandidateError(f"Artefacte amb enllaç simbòlic: {name}")
    return ReleaseCandidatePlan(resolved, profile)


class ReleaseCandidateBuilder:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise ReleaseCandidateError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def prepare(self, plan: ReleaseCandidatePlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in REQUIRED_OUTPUTS)
        if dry_run:
            return targets
        manifest = json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        notes = (
            "# XAAC Thin Client OS 1.0.0-rc.1\n\n"
            "Primera release candidate congelada del sistema. Només s'admeten correccions "
            "crítiques, de seguretat, documentació imprescindible i regressions demostrades.\n\n"
            "## Validació requerida\n\n"
            + "\n".join(f"- {name}: `{command}`" for name, command in plan.profile["gates"].items())
            + "\n"
        )
        approval = json.dumps(
            {
                "schema_version": 1,
                "version": plan.profile["version"],
                "status": "pending",
                "required_roles": plan.profile["approval"]["roles"],
                "approvals": [],
                "release_blocked": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        commands = "\n".join(plan.profile["gates"].values())
        script = f'''#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
{commands}
python - <<'PYVERIFY'
import json
from pathlib import Path
approval=json.loads(Path('.build/release-candidate/approval.json').read_text())
if approval.get('status') != 'approved' or approval.get('release_blocked', True):
    raise SystemExit('Release candidate pendent d’aprovació')
PYVERIFY
'''
        self._write(targets[0], manifest, 0o644)
        self._write(targets[1], notes, 0o644)
        self._write(targets[2], approval, 0o640)
        self._write(targets[3], script, 0o750)
        return targets
