"""Deterministic hybrid ISO constructor for phase 12.1."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class IsoBuilderError(RuntimeError):
    """Raised when the production ISO policy is incomplete or unsafe."""


_REQUIRED_OUTPUTS = {"staging", "iso", "checksum", "signature", "manifest", "build_script"}


def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise IsoBuilderError(f"Ruta relativa invàlida en {field}")
    parts = PurePosixPath(value).parts
    if ".." in parts or "." in parts:
        raise IsoBuilderError(f"Ruta insegura en {field}")
    return value


def load_iso_builder(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise IsoBuilderError(f"No s'ha pogut carregar la política ISO: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise IsoBuilderError("Política ISO invàlida")
    if raw.get("product") != "XAAC Thin Client OS" or raw.get("architecture") != "amd64":
        raise IsoBuilderError("Producte o arquitectura ISO no suportats")
    if raw.get("hardware_profile") != "wyse3040":
        raise IsoBuilderError("Perfil ISO no suportat")

    image = raw.get("image")
    if not isinstance(image, dict) or image.get("format") != "iso-hybrid":
        raise IsoBuilderError("Format ISO invàlid")
    if image.get("uefi") is not True or image.get("bios_compatibility") is not True:
        raise IsoBuilderError("La ISO híbrida ha d'incloure UEFI i BIOS")
    volume_id = image.get("volume_id")
    if not isinstance(volume_id, str) or not volume_id or len(volume_id) > 32 or not volume_id.replace("_", "").isalnum():
        raise IsoBuilderError("Identificador de volum ISO invàlid")

    boot = raw.get("boot")
    if not isinstance(boot, dict) or boot.get("loader") != "grub2":
        raise IsoBuilderError("Carregador ISO invàlid")
    if boot.get("default_entry") != "installer" or boot.get("timeout_seconds") not in range(1, 61):
        raise IsoBuilderError("Configuració d'arrencada ISO invàlida")
    entries = boot.get("entries")
    if not isinstance(entries, list) or {entry.get("id") for entry in entries if isinstance(entry, dict)} != {"installer", "diagnostics"}:
        raise IsoBuilderError("La ISO necessita entrades installer i diagnostics")
    for entry in entries:
        if not isinstance(entry.get("kernel_parameters"), list) or not all(isinstance(v, str) and v for v in entry["kernel_parameters"]):
            raise IsoBuilderError("Paràmetres d'arrencada ISO invàlids")

    live = raw.get("live")
    if not isinstance(live, dict) or live.get("diagnostics_only") is not True:
        raise IsoBuilderError("El mode live ha de ser exclusivament de diagnòstic")
    if live.get("read_only_root") is not True or live.get("persistent_changes") is not False:
        raise IsoBuilderError("El mode live no pot persistir canvis")
    if live.get("allow_shell") is not False or live.get("allow_install") is not False:
        raise IsoBuilderError("Mode live de diagnòstic massa permissiu")

    integrity = raw.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("hash_algorithm") != "sha256":
        raise IsoBuilderError("Integritat ISO invàlida")
    if integrity.get("require_signature") is not True or integrity.get("detached_signature") is not True:
        raise IsoBuilderError("La ISO ha d'estar signada")
    key_id = integrity.get("signing_key_id")
    if not isinstance(key_id, str) or not key_id or any(c.isspace() for c in key_id):
        raise IsoBuilderError("Identificador de clau de signatura invàlid")

    sources = raw.get("sources")
    if not isinstance(sources, dict):
        raise IsoBuilderError("Fonts ISO absents")
    for key in ("rootfs", "kernel", "initramfs", "efi_image", "bios_image", "installer"):
        sources[key] = _safe_relative(sources.get(key), f"sources.{key}")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != _REQUIRED_OUTPUTS:
        raise IsoBuilderError("outputs ISO incomplet")
    raw["outputs"] = {key: _safe_relative(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class IsoBuildPlan:
    project_root: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.project_root / self.profile["outputs"][key]

    def source(self, key: str) -> Path:
        return self.project_root / self.profile["sources"][key]

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "image_id": self.profile["image_id"],
            "format": "iso-hybrid",
            "architecture": "amd64",
            "hardware_profile": "wyse3040",
            "uefi": True,
            "installer": True,
            "diagnostics_live": True,
            "hash_algorithm": "sha256",
            "signature_required": True,
        }


def create_iso_build_plan(project_root: Path, profile_path: Path) -> IsoBuildPlan:
    root = project_root.resolve()
    if root == Path("/"):
        raise IsoBuilderError(f"Arrel de projecte insegura: {root}")
    return IsoBuildPlan(root, load_iso_builder(profile_path))


class IsoBuilder:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise IsoBuilderError(f"Destinació amb enllaç simbòlic: {path}")
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

    def prepare(self, plan: IsoBuildPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in ("staging", "iso", "checksum", "signature", "manifest", "build_script"))
        if dry_run:
            return targets

        staging = plan.output("staging")
        if staging.is_symlink():
            raise IsoBuilderError(f"Destinació amb enllaç simbòlic: {staging}")
        staging.mkdir(parents=True, exist_ok=True)
        grub = staging / "boot/grub/grub.cfg"
        entries = {entry["id"]: entry for entry in plan.profile["boot"]["entries"]}
        installer_params = " ".join(entries["installer"]["kernel_parameters"])
        diagnostics_params = " ".join(entries["diagnostics"]["kernel_parameters"])
        grub_content = (
            f"set timeout={plan.profile['boot']['timeout_seconds']}\nset default=0\n\n"
            "menuentry 'Install XAAC Thin Client OS' {\n"
            f"  linux /live/vmlinuz {installer_params}\n  initrd /live/initrd.img\n}}\n\n"
            "menuentry 'XAAC diagnostics (read-only)' {\n"
            f"  linux /live/vmlinuz {diagnostics_params}\n  initrd /live/initrd.img\n}}\n"
        )
        self._write(grub, grub_content, 0o644)

        manifest_path = plan.output("manifest")
        self._write(manifest_path, json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o644)
        p = plan.profile
        script = f"""#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
STAGING="$ROOT/{p['outputs']['staging']}"
ISO="$ROOT/{p['outputs']['iso']}"
CHECKSUM="$ROOT/{p['outputs']['checksum']}"
SIGNATURE="$ROOT/{p['outputs']['signature']}"
for source in {p['sources']['rootfs']} {p['sources']['kernel']} {p['sources']['initramfs']} {p['sources']['efi_image']} {p['sources']['bios_image']} {p['sources']['installer']}; do
  [ -e "$ROOT/$source" ] || {{ echo "Missing ISO source: $source" >&2; exit 2; }}
done
install -Dm0644 "$ROOT/{p['sources']['kernel']}" "$STAGING/live/vmlinuz"
install -Dm0644 "$ROOT/{p['sources']['initramfs']}" "$STAGING/live/initrd.img"
install -Dm0644 "$ROOT/{p['sources']['rootfs']}" "$STAGING/live/filesystem.squashfs"
install -Dm0755 "$ROOT/{p['sources']['installer']}" "$STAGING/install/xaac-installer"
mkdir -p "$(dirname "$ISO")"
xorriso -as mkisofs -r -J -joliet-long -V '{p['image']['volume_id']}' \
  -o "$ISO" -isohybrid-mbr "$ROOT/{p['sources']['bios_image']}" \
  -partition_offset 16 -append_partition 2 0xef "$ROOT/{p['sources']['efi_image']}" \
  -appended_part_as_gpt -iso_mbr_part_type a2a0d0ebe5b9334487c068b6b72699c7 \
  -c boot/boot.cat -b boot/grub/i386-pc/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table \
  -eltorito-alt-boot -e --interval:appended_partition_2:all:: -no-emul-boot -isohybrid-gpt-basdat "$STAGING"
sha256sum "$ISO" > "$CHECKSUM"
gpg --batch --yes --local-user '{p['integrity']['signing_key_id']}' --detach-sign --armor --output "$SIGNATURE" "$ISO"
"""
        self._write(plan.output("build_script"), script, 0o750)
        return targets

    @staticmethod
    def checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
