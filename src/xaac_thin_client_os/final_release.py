"""Final 1.1.0 release plan and publication assets for phase 12.12."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class FinalReleaseError(RuntimeError):
    """Raised when the final release configuration is incomplete or unsafe."""


REQUIRED_ARTIFACTS = (
    "iso", "img", "recovery_img", "pxe", "packages", "documentation",
)
REQUIRED_SECURITY = ("hash_algorithm", "detached_signatures", "signing_key_env")
REQUIRED_OUTPUTS = ("manifest", "notes", "announcement", "release_script", "verify_script")


def _relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise FinalReleaseError(f"Ruta relativa invàlida en {field}")
    if any(part in {".", ".."} for part in PurePosixPath(value).parts):
        raise FinalReleaseError(f"Ruta insegura en {field}")
    return value


def load_final_release_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FinalReleaseError(f"No s'ha pogut carregar el perfil final: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise FinalReleaseError("Perfil de release final invàlid")
    if raw.get("product") != "XAAC Thin Client OS" or raw.get("version") != "1.1.0":
        raise FinalReleaseError("Producte o versió final invàlids")
    if raw.get("status") != "stable" or raw.get("channel") != "production":
        raise FinalReleaseError("La release final ha de ser stable i production")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, dict) or tuple(artifacts) != REQUIRED_ARTIFACTS:
        raise FinalReleaseError("Conjunt d'artefactes finals incomplet o desordenat")
    raw["artifacts"] = {k: _relative(v, f"artifacts.{k}") for k, v in artifacts.items()}
    security = raw.get("security")
    if not isinstance(security, dict) or tuple(security) != REQUIRED_SECURITY:
        raise FinalReleaseError("Configuració de hashes i signatures incompleta")
    if security["hash_algorithm"] != "sha256" or security["detached_signatures"] is not True:
        raise FinalReleaseError("SHA-256 i signatures separades són obligatoris")
    if not isinstance(security["signing_key_env"], str) or not security["signing_key_env"]:
        raise FinalReleaseError("Variable de clau de signatura invàlida")
    approval = raw.get("approval")
    if not isinstance(approval, dict) or approval.get("rc_status_file") is None:
        raise FinalReleaseError("Aprovació de la release candidate no configurada")
    approval["rc_status_file"] = _relative(approval["rc_status_file"], "approval.rc_status_file")
    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or tuple(outputs) != REQUIRED_OUTPUTS:
        raise FinalReleaseError("Outputs de release final incomplets o desordenats")
    raw["outputs"] = {k: _relative(v, f"outputs.{k}") for k, v in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class FinalReleasePlan:
    root: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.root / self.profile["outputs"][key]

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "product": self.profile["product"],
            "version": self.profile["version"],
            "status": self.profile["status"],
            "channel": self.profile["channel"],
            "artifacts": self.profile["artifacts"],
            "hash_algorithm": "sha256",
            "detached_signatures": True,
            "documentation_included": True,
            "release_candidate_approval_required": True,
        }


def create_final_release_plan(root: Path, profile_path: Path) -> FinalReleasePlan:
    resolved = root.resolve()
    if resolved == Path("/"):
        raise FinalReleaseError(f"Arrel insegura: {resolved}")
    profile = load_final_release_profile(profile_path)
    for name, rel in {**profile["artifacts"], **profile["outputs"]}.items():
        if (resolved / rel).is_symlink():
            raise FinalReleaseError(f"Ruta amb enllaç simbòlic: {name}")
    return FinalReleasePlan(resolved, profile)


class FinalReleaseBuilder:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise FinalReleaseError(f"Destinació amb enllaç simbòlic: {path}")
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

    def prepare(self, plan: FinalReleasePlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in REQUIRED_OUTPUTS)
        if dry_run:
            return targets
        manifest = json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        notes = (
            "# XAAC Thin Client OS 1.1.0\n\n"
            "Primera versió estable de producció per al Dell Wyse 3040. Inclou ISO, IMG, "
            "imatge de recuperació, PXE, paquets Debian, hashes, signatures i documentació.\n"
        )
        announcement = (
            "# Publicació de XAAC Thin Client OS 1.1.0\n\n"
            "XAAC Thin Client OS 1.1.0 està preparat per a instal·lació, clonació, "
            "administració, actualització i recuperació en Dell Wyse 3040.\n\n"
            "Abans del desplegament, verifiqueu `SHA256SUMS` i les signatures `.asc`.\n"
        )
        artifacts = " ".join(f'"{rel}"' for rel in plan.profile["artifacts"].values())
        key_env = plan.profile["security"]["signing_key_env"]
        approval = plan.profile["approval"]["rc_status_file"]
        release_script = f'''#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$ROOT"
: "${{{key_env}:?Cal definir {key_env}}}"
python - <<'PYAPPROVAL'
import json
from pathlib import Path
p=Path({approval!r})
data=json.loads(p.read_text(encoding='utf-8'))
if data.get('status') != 'approved' or data.get('release_blocked', True):
    raise SystemExit('La release candidate no està aprovada')
PYAPPROVAL
for artifact in {artifacts}; do
    test -e "$artifact" || {{ echo "Falta l’artefacte: $artifact" >&2; exit 1; }}
done
OUT=.build/release-1.1.0
mkdir -p "$OUT"
sha256sum {artifacts} > "$OUT/SHA256SUMS"
gpg --batch --yes --local-user "${{{key_env}}}" --armor --detach-sign "$OUT/SHA256SUMS"
for artifact in {artifacts}; do
    gpg --batch --yes --local-user "${{{key_env}}}" --armor --detach-sign "$artifact"
done
cp .build/final-release/manifest.json "$OUT/manifest.json"
cp .build/final-release/RELEASE_NOTES.md "$OUT/RELEASE_NOTES.md"
cp .build/final-release/ANNOUNCEMENT.md "$OUT/ANNOUNCEMENT.md"
'''
        verify_script = f'''#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$ROOT"
OUT=.build/release-1.1.0
test "$(cat VERSION)" = "1.1.0"
sha256sum -c "$OUT/SHA256SUMS"
gpg --verify "$OUT/SHA256SUMS.asc" "$OUT/SHA256SUMS"
for artifact in {artifacts}; do
    gpg --verify "$artifact.asc" "$artifact"
done
'''
        self._write(targets[0], manifest, 0o644)
        self._write(targets[1], notes, 0o644)
        self._write(targets[2], announcement, 0o644)
        self._write(targets[3], release_script, 0o750)
        self._write(targets[4], verify_script, 0o750)
        return targets
