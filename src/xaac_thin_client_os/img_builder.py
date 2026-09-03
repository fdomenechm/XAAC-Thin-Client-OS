"""Deterministic raw IMG constructor for phase 12.2."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class ImgBuilderError(RuntimeError):
    """Raised when the production IMG policy is incomplete or unsafe."""


def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ImgBuilderError(f"Ruta relativa invàlida en {field}")
    if any(part in {".", ".."} for part in PurePosixPath(value).parts):
        raise ImgBuilderError(f"Ruta insegura en {field}")
    return value


def load_img_builder(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ImgBuilderError(f"No s'ha pogut carregar la política IMG: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ImgBuilderError("Política IMG invàlida")
    if raw.get("product") != "XAAC Thin Client OS" or raw.get("architecture") != "amd64":
        raise ImgBuilderError("Producte o arquitectura IMG no suportats")
    if raw.get("hardware_profile") != "wyse3040":
        raise ImgBuilderError("Perfil IMG no suportat")
    image = raw.get("image")
    if not isinstance(image, dict) or image.get("format") != "raw-img":
        raise ImgBuilderError("Format IMG invàlid")
    if not isinstance(image.get("size_mib"), int) or image["size_mib"] < 4096:
        raise ImgBuilderError("Mida IMG insuficient")
    if image.get("partition_table") != "gpt" or image.get("boot_mode") != "uefi":
        raise ImgBuilderError("La IMG ha d'utilitzar GPT i UEFI")
    partitions = raw.get("partitions")
    if not isinstance(partitions, list) or len(partitions) != 4:
        raise ImgBuilderError("Esquema de particions IMG incomplet")
    expected = ["efi", "root", "data", "recovery"]
    if [p.get("id") for p in partitions if isinstance(p, dict)] != expected:
        raise ImgBuilderError("Ordre de particions IMG invàlid")
    if sum(int(p.get("size_mib", 0)) for p in partitions) >= image["size_mib"]:
        raise ImgBuilderError("Les particions no caben en la IMG")
    if partitions[1].get("expand_on_first_boot") is not True:
        raise ImgBuilderError("La partició arrel s'ha d'expandir al primer inici")
    cloning = raw.get("cloning")
    if not isinstance(cloning, dict) or cloning.get("master_image") is not True:
        raise ImgBuilderError("Política de clonació IMG invàlida")
    required_ids = {"machine-id", "device-uuid", "ssh-host-keys", "filesystem-uuids"}
    if set(cloning.get("regenerate_on_first_boot", [])) != required_ids:
        raise ImgBuilderError("Identificadors de primer inici incomplets")
    if cloning.get("remove_identity_before_publish") is not True:
        raise ImgBuilderError("La imatge mestra ha d'eliminar la identitat")
    sources = raw.get("sources")
    if not isinstance(sources, dict):
        raise ImgBuilderError("Fonts IMG absents")
    for key in ("rootfs", "efi_tree", "recovery_image"):
        sources[key] = _safe_relative(sources.get(key), f"sources.{key}")
    outputs = raw.get("outputs")
    required_outputs = {"image", "compressed", "checksum", "manifest", "build_script", "first_boot_script"}
    if not isinstance(outputs, dict) or set(outputs) != required_outputs:
        raise ImgBuilderError("outputs IMG incomplet")
    raw["outputs"] = {k: _safe_relative(v, f"outputs.{k}") for k, v in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class ImgBuildPlan:
    project_root: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.project_root / self.profile["outputs"][key]

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "image_id": self.profile["image_id"],
            "format": "raw-img",
            "architecture": "amd64",
            "hardware_profile": "wyse3040",
            "partition_table": "gpt",
            "uefi": True,
            "expand_on_first_boot": True,
            "clone_ready": True,
            "identity_regeneration": sorted(self.profile["cloning"]["regenerate_on_first_boot"]),
        }


def create_img_build_plan(project_root: Path, profile_path: Path) -> ImgBuildPlan:
    root = project_root.resolve()
    if root == Path("/"):
        raise ImgBuilderError(f"Arrel de projecte insegura: {root}")
    return ImgBuildPlan(root, load_img_builder(profile_path))


class ImgBuilder:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise ImgBuilderError(f"Destinació amb enllaç simbòlic: {path}")
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

    def prepare(self, plan: ImgBuildPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        keys = ("image", "compressed", "checksum", "manifest", "build_script", "first_boot_script")
        targets = tuple(plan.output(key) for key in keys)
        if dry_run:
            return targets
        self._write(plan.output("manifest"), json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o644)
        first_boot = """#!/bin/sh
set -eu
FLAG=/var/lib/xaac/first-boot-img.done
[ ! -e \"$FLAG\" ] || exit 0
rootdev=$(findmnt -n -o SOURCE /)
partnum=$(lsblk -no PARTN \"$rootdev\")
disk=$(lsblk -no PKNAME \"$rootdev\")
growpart \"/dev/$disk\" \"$partnum\"
resize2fs \"$rootdev\"
rm -f /etc/machine-id
systemd-machine-id-setup
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
xaac-os configure-device-identity
mkdir -p \"$(dirname \"$FLAG\")\"
: > \"$FLAG\"
"""
        self._write(plan.output("first_boot_script"), first_boot, 0o750)
        p = plan.profile
        parts = p["partitions"]
        script = f"""#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- \"$(dirname -- \"$0\")/../..\" && pwd)
IMG=\"$ROOT/{p['outputs']['image']}\"
COMPRESSED=\"$ROOT/{p['outputs']['compressed']}\"
CHECKSUM=\"$ROOT/{p['outputs']['checksum']}\"
ROOTFS=\"$ROOT/{p['sources']['rootfs']}\"
EFI_TREE=\"$ROOT/{p['sources']['efi_tree']}\"
RECOVERY=\"$ROOT/{p['sources']['recovery_image']}\"
for source in \"$ROOTFS\" \"$EFI_TREE\" \"$RECOVERY\"; do [ -e \"$source\" ] || {{ echo \"Missing IMG source: $source\" >&2; exit 2; }}; done
mkdir -p \"$(dirname \"$IMG\")\"
truncate -s {p['image']['size_mib']}M \"$IMG\"
sgdisk --zap-all \"$IMG\"
sgdisk -n 1:1MiB:+{parts[0]['size_mib']}MiB -t 1:ef00 -c 1:XAAC_EFI \"$IMG\"
sgdisk -n 2:0:+{parts[1]['size_mib']}MiB -t 2:8300 -c 2:XAAC_ROOT \"$IMG\"
sgdisk -n 3:0:+{parts[2]['size_mib']}MiB -t 3:8300 -c 3:XAAC_DATA \"$IMG\"
sgdisk -n 4:0:+{parts[3]['size_mib']}MiB -t 4:8300 -c 4:XAAC_RECOVERY \"$IMG\"
LOOP=$(losetup --find --show --partscan \"$IMG\")
trap 'losetup -d \"$LOOP\"' EXIT
mkfs.vfat -F 32 -n XAAC_EFI \"${{LOOP}}p1\"
mkfs.ext4 -F -L XAAC_ROOT \"${{LOOP}}p2\"
mkfs.ext4 -F -L XAAC_DATA \"${{LOOP}}p3\"
dd if=\"$RECOVERY\" of=\"${{LOOP}}p4\" bs=4M conv=fsync,status=none
MNT=$(mktemp -d)
trap 'umount \"$MNT/efi\" 2>/dev/null || true; umount \"$MNT\" 2>/dev/null || true; rmdir \"$MNT/efi\" \"$MNT\" 2>/dev/null || true; losetup -d \"$LOOP\"' EXIT
mount \"${{LOOP}}p2\" \"$MNT\"
tar -C \"$MNT\" -xpf \"$ROOTFS\"
mkdir -p \"$MNT/efi\"; mount \"${{LOOP}}p1\" \"$MNT/efi\"; cp -a \"$EFI_TREE/.\" \"$MNT/efi/\"
rm -f \"$MNT/etc/machine-id\" \"$MNT/etc/ssh/ssh_host_\"*
install -Dm0750 \"$ROOT/{p['outputs']['first_boot_script']}\" \"$MNT/usr/libexec/xaac/xaac-img-first-boot\"
sync
xz -T0 -9 -c \"$IMG\" > \"$COMPRESSED\"
sha256sum \"$IMG\" \"$COMPRESSED\" > \"$CHECKSUM\"
"""
        self._write(plan.output("build_script"), script, 0o750)
        return targets
