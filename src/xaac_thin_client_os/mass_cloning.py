"""Deterministic mass-cloning assets for phase 12.5."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class MassCloningError(RuntimeError):
    """Raised when mass-cloning policy is incomplete or unsafe."""

def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise MassCloningError(f"Ruta relativa invàlida en {field}")
    if any(part in {".", ".."} for part in PurePosixPath(value).parts):
        raise MassCloningError(f"Ruta insegura en {field}")
    return value

def load_mass_cloning(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MassCloningError(f"No s'ha pogut carregar la política de clonació: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise MassCloningError("Política de clonació invàlida")
    if raw.get("product") != "XAAC Thin Client OS" or raw.get("architecture") != "amd64":
        raise MassCloningError("Producte o arquitectura no suportats")
    if raw.get("hardware_profile") != "wyse3040":
        raise MassCloningError("Perfil de maquinari no suportat")
    master = raw.get("master_image")
    if not isinstance(master, dict) or master.get("verify_sha256") is not True:
        raise MassCloningError("La verificació SHA-256 de la imatge mestra és obligatòria")
    sanitation = raw.get("sanitization")
    required_sanitation = ("require_offline_rootfs", "remove_machine_id", "remove_ssh_host_keys", "remove_xaac_identity", "remove_xms_enrollment", "clear_logs", "clear_random_seed", "mark_first_boot")
    if not isinstance(sanitation, dict) or any(sanitation.get(key) is not True for key in required_sanitation):
        raise MassCloningError("Sanejament obligatori incomplet")
    first_boot = raw.get("first_boot")
    required_first_boot = ("regenerate_machine_id", "regenerate_ssh_host_keys", "regenerate_xaac_identity", "regenerate_filesystem_uuid", "require_unique_identity")
    if not isinstance(first_boot, dict) or any(first_boot.get(key) is not True for key in required_first_boot):
        raise MassCloningError("Regeneració d'identitat incompleta")
    verification = raw.get("verification")
    labels = ["XAAC_EFI", "XAAC_ROOT", "XAAC_DATA", "XAAC_RECOVERY"]
    if not isinstance(verification, dict) or verification.get("required_labels") != labels:
        raise MassCloningError("Verificació de particions incompleta")
    deployment = raw.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("exact_confirmation_phrase") != "CLONE XAAC":
        raise MassCloningError("Frase de confirmació de clonació invàlida")
    if not isinstance(deployment.get("parallel_jobs"), int) or not 1 <= deployment["parallel_jobs"] <= 16:
        raise MassCloningError("Nombre de treballs paral·lels invàlid")
    for key in ("reject_source_device", "reject_mounted_targets", "verify_after_write"):
        if deployment.get(key) is not True:
            raise MassCloningError(f"Control de desplegament obligatori absent: {key}")
    outputs = raw.get("outputs")
    required_outputs = {"manifest", "sanitize_script", "clone_script", "verify_script"}
    if not isinstance(outputs, dict) or set(outputs) != required_outputs:
        raise MassCloningError("outputs de clonació incomplets")
    raw["outputs"] = {key: _safe_relative(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw

@dataclass(frozen=True, slots=True)
class MassCloningPlan:
    project_root: Path
    profile: dict[str, Any]
    def output(self, key: str) -> Path:
        return self.project_root / self.profile["outputs"][key]
    def manifest(self) -> dict[str, object]:
        return {"schema_version": 1, "profile_id": self.profile["profile_id"], "product": "XAAC Thin Client OS", "architecture": "amd64", "hardware_profile": "wyse3040", "master_image": self.profile["master_image"]["source"], "parallel_jobs": self.profile["deployment"]["parallel_jobs"], "confirmation_phrase": "CLONE XAAC", "required_labels": self.profile["verification"]["required_labels"], "steps": ["verify-master", "sanitize", "clone", "first-boot-identity", "verify-clones"]}

def create_mass_cloning_plan(project_root: Path, profile_path: Path) -> MassCloningPlan:
    root = project_root.resolve()
    if root == Path("/"):
        raise MassCloningError(f"Arrel de projecte insegura: {root}")
    return MassCloningPlan(root, load_mass_cloning(profile_path))

class MassCloningBuilder:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise MassCloningError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream: stream.write(content)
            os.chmod(temporary, mode); os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    def prepare(self, plan: MassCloningPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        keys = ("manifest", "sanitize_script", "clone_script", "verify_script")
        targets = tuple(plan.output(key) for key in keys)
        if dry_run: return targets
        self._write(plan.output("manifest"), json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o644)
        sanitize = r'''#!/bin/sh
set -eu
ROOT=${1:-}
[ "$(id -u)" -eq 0 ] || { echo "root privileges required" >&2; exit 1; }
[ -d "$ROOT/etc" ] || { echo "offline rootfs required" >&2; exit 1; }
findmnt -nro TARGET "$ROOT" >/dev/null 2>&1 || { echo "rootfs is not mounted" >&2; exit 1; }
: > "$ROOT/etc/machine-id"
rm -f "$ROOT/var/lib/dbus/machine-id" "$ROOT"/etc/ssh/ssh_host_* "$ROOT/var/lib/systemd/random-seed"
rm -rf "$ROOT/var/lib/xaac/identity" "$ROOT/var/lib/xaac/enrollment"
find "$ROOT/var/log" -mindepth 1 -delete
install -d -m 0700 "$ROOT/var/lib/xaac"
touch "$ROOT/etc/xaac-first-boot.pending"
sync
'''
        clone = r'''#!/bin/sh
set -eu
IMAGE=${1:-}
CONFIRM=${2:-}
shift 2 || true
[ "$(id -u)" -eq 0 ] || { echo "root privileges required" >&2; exit 1; }
[ "$CONFIRM" = "CLONE XAAC" ] || { echo "confirmation phrase rejected" >&2; exit 1; }
[ -f "$IMAGE" ] && [ -f "$IMAGE.sha256" ] || { echo "master image is incomplete" >&2; exit 1; }
(cd "$(dirname "$IMAGE")" && sha256sum -c "$(basename "$IMAGE").sha256")
[ "$#" -gt 0 ] || { echo "no target devices" >&2; exit 1; }
for target in "$@"; do
  [ -b "$target" ] || { echo "invalid target: $target" >&2; exit 1; }
  findmnt -rn -S "$target" >/dev/null 2>&1 && { echo "mounted target: $target" >&2; exit 1; }
  [ "$(readlink -f "$target")" != "$(readlink -f "$IMAGE")" ] || { echo "source device rejected" >&2; exit 1; }
done
for target in "$@"; do dd if="$IMAGE" of="$target" bs=16M conv=fsync,status=progress; done
for target in "$@"; do cmp -n "$(stat -c %s "$IMAGE")" "$IMAGE" "$target"; done
sync
'''
        verify = r'''#!/bin/sh
set -eu
TARGET=${1:-}
[ -b "$TARGET" ] || { echo "target is not a block device" >&2; exit 1; }
for label in XAAC_EFI XAAC_ROOT XAAC_DATA XAAC_RECOVERY; do
  blkid -L "$label" >/dev/null 2>&1 || { echo "missing partition label: $label" >&2; exit 1; }
done
sgdisk -v "$TARGET"
echo "clone verification passed: $TARGET"
'''
        self._write(plan.output("sanitize_script"), sanitize, 0o750)
        self._write(plan.output("clone_script"), clone, 0o750)
        self._write(plan.output("verify_script"), verify, 0o750)
        return targets
