"""Deterministic PXE production package constructor for phase 12.3."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class PxeBuilderError(RuntimeError):
    """Raised when the PXE production package policy is incomplete or unsafe."""


def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise PxeBuilderError(f"Ruta relativa invàlida en {field}")
    if any(part in {".", ".."} for part in PurePosixPath(value).parts):
        raise PxeBuilderError(f"Ruta insegura en {field}")
    return value


def load_pxe_builder(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PxeBuilderError(f"No s'ha pogut carregar la política PXE: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise PxeBuilderError("Política PXE invàlida")
    if raw.get("product") != "XAAC Thin Client OS" or raw.get("architecture") != "amd64":
        raise PxeBuilderError("Producte o arquitectura PXE no suportats")
    if raw.get("hardware_profile") != "wyse3040":
        raise PxeBuilderError("Perfil PXE no suportat")
    package = raw.get("package")
    if not isinstance(package, dict) or package.get("format") != "pxe-bundle":
        raise PxeBuilderError("Format de paquet PXE invàlid")
    if package.get("loader") != "ipxe" or package.get("transport") not in {"http", "https", "tftp"}:
        raise PxeBuilderError("Carregador o transport PXE no suportat")
    unattended = raw.get("unattended_install")
    if not isinstance(unattended, dict) or unattended.get("enabled") is not True:
        raise PxeBuilderError("La instal·lació desatesa és obligatòria")
    if unattended.get("require_confirmation_token") is not True:
        raise PxeBuilderError("La instal·lació desatesa ha d'exigir un token")
    if unattended.get("wipe_target_disk") is not True:
        raise PxeBuilderError("La política PXE ha de declarar l'esborrat del disc")
    if unattended.get("target_profile") != "wyse3040":
        raise PxeBuilderError("Perfil de destinació desatesa invàlid")
    sources = raw.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"kernel", "initramfs", "rootfs"}:
        raise PxeBuilderError("Fonts PXE incompletes")
    raw["sources"] = {key: _safe_relative(value, f"sources.{key}") for key, value in sources.items()}
    outputs = raw.get("outputs")
    required_outputs = {"bundle", "manifest", "ipxe_script", "unattended_config", "build_script", "checksum"}
    if not isinstance(outputs, dict) or set(outputs) != required_outputs:
        raise PxeBuilderError("outputs PXE incomplet")
    raw["outputs"] = {key: _safe_relative(value, f"outputs.{key}") for key, value in outputs.items()}
    boot = raw.get("boot")
    if not isinstance(boot, dict) or not isinstance(boot.get("kernel_arguments"), list):
        raise PxeBuilderError("Configuració d'arrencada PXE invàlida")
    required_args = {"boot=live", "xaac.install=unattended", "xaac.profile=wyse3040"}
    if not required_args.issubset(set(boot["kernel_arguments"])):
        raise PxeBuilderError("Arguments d'arrencada PXE incomplets")
    return raw


@dataclass(frozen=True, slots=True)
class PxeBuildPlan:
    project_root: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.project_root / self.profile["outputs"][key]

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "package_id": self.profile["package_id"],
            "format": "pxe-bundle",
            "architecture": "amd64",
            "hardware_profile": "wyse3040",
            "loader": "ipxe",
            "transport": self.profile["package"]["transport"],
            "unattended_install": True,
            "confirmation_token_required": True,
            "components": ["kernel", "initramfs", "rootfs", "ipxe", "unattended-config"],
        }


def create_pxe_build_plan(project_root: Path, profile_path: Path) -> PxeBuildPlan:
    root = project_root.resolve()
    if root == Path("/"):
        raise PxeBuilderError(f"Arrel de projecte insegura: {root}")
    return PxeBuildPlan(root, load_pxe_builder(profile_path))


class PxeBuilder:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise PxeBuilderError(f"Destinació amb enllaç simbòlic: {path}")
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

    def prepare(self, plan: PxeBuildPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        keys = ("bundle", "manifest", "ipxe_script", "unattended_config", "build_script", "checksum")
        targets = tuple(plan.output(key) for key in keys)
        if dry_run:
            return targets
        self._write(plan.output("manifest"), json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o644)
        args = " ".join(plan.profile["boot"]["kernel_arguments"])
        ipxe = f"""#!ipxe
set base-url ${{base-url}}
isset ${{base-url}} || set base-url http://${{next-server}}/xaac
kernel ${{base-url}}/vmlinuz initrd=initrd.img {args} xaac.confirmation-token=${{confirmation-token}} || exit
initrd ${{base-url}}/initrd.img || exit
boot || exit
"""
        self._write(plan.output("ipxe_script"), ipxe, 0o644)
        unattended = {
            "schema_version": 1,
            "mode": "unattended",
            "hardware_profile": "wyse3040",
            "target_disk": "auto-emmc",
            "wipe_target_disk": True,
            "confirmation_token_required": True,
            "partition_layout": "production-gpt",
            "post_install": ["regenerate-machine-id", "regenerate-ssh-host-keys", "configure-device-identity"],
        }
        self._write(plan.output("unattended_config"), json.dumps(unattended, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        p = plan.profile
        script = f"""#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
BUNDLE="$ROOT/{p['outputs']['bundle']}"
MANIFEST="$ROOT/{p['outputs']['manifest']}"
IPXE="$ROOT/{p['outputs']['ipxe_script']}"
UNATTENDED="$ROOT/{p['outputs']['unattended_config']}"
CHECKSUM="$ROOT/{p['outputs']['checksum']}"
KERNEL="$ROOT/{p['sources']['kernel']}"
INITRAMFS="$ROOT/{p['sources']['initramfs']}"
ROOTFS="$ROOT/{p['sources']['rootfs']}"
for source in "$KERNEL" "$INITRAMFS" "$ROOTFS" "$MANIFEST" "$IPXE" "$UNATTENDED"; do
  [ -f "$source" ] || {{ echo "Missing PXE source: $source" >&2; exit 2; }}
done
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/config"
install -m0644 "$KERNEL" "$BUNDLE/vmlinuz"
install -m0644 "$INITRAMFS" "$BUNDLE/initrd.img"
install -m0644 "$ROOTFS" "$BUNDLE/rootfs.squashfs"
install -m0644 "$IPXE" "$BUNDLE/boot.ipxe"
install -m0640 "$UNATTENDED" "$BUNDLE/config/unattended.json"
install -m0644 "$MANIFEST" "$BUNDLE/manifest.json"
(cd "$BUNDLE" && find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$CHECKSUM"
"""
        self._write(plan.output("build_script"), script, 0o750)
        return targets
