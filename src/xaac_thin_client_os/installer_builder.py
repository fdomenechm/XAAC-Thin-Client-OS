"""Deterministic production installer constructor for phase 12.4."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class InstallerBuilderError(RuntimeError):
    """Raised when the production installer policy is incomplete or unsafe."""


def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise InstallerBuilderError(f"Ruta relativa invàlida en {field}")
    if any(part in {".", ".."} for part in PurePosixPath(value).parts):
        raise InstallerBuilderError(f"Ruta insegura en {field}")
    return value


def load_installer_builder(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InstallerBuilderError(f"No s'ha pogut carregar la política de l'instal·lador: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise InstallerBuilderError("Política de l'instal·lador invàlida")
    if raw.get("product") != "XAAC Thin Client OS" or raw.get("architecture") != "amd64":
        raise InstallerBuilderError("Producte o arquitectura no suportats")
    if raw.get("hardware_profile") != "wyse3040":
        raise InstallerBuilderError("Perfil de maquinari no suportat")
    safety = raw.get("safety")
    if not isinstance(safety, dict):
        raise InstallerBuilderError("Política de seguretat absent")
    required_safety = {
        "explicit_disk_selection": True,
        "exact_confirmation_phrase": True,
        "reject_mounted_target": True,
        "reject_running_system_disk": True,
        "require_ac_power": True,
    }
    for key, expected in required_safety.items():
        if safety.get(key) is not expected:
            raise InstallerBuilderError(f"Control de seguretat obligatori absent: {key}")
    if safety.get("confirmation_phrase") != "INSTALL XAAC":
        raise InstallerBuilderError("Frase de confirmació invàlida")
    layout = raw.get("partition_layout")
    if not isinstance(layout, dict) or layout.get("table") != "gpt":
        raise InstallerBuilderError("Esquema de particions invàlid")
    partitions = layout.get("partitions")
    required_labels = ["XAAC_EFI", "XAAC_ROOT", "XAAC_DATA", "XAAC_RECOVERY"]
    if not isinstance(partitions, list) or [item.get("label") for item in partitions if isinstance(item, dict)] != required_labels:
        raise InstallerBuilderError("Particions de producció incompletes o desordenades")
    if layout.get("minimum_disk_mib") != 7168:
        raise InstallerBuilderError("Mida mínima de disc invàlida")
    copy = raw.get("copy")
    if not isinstance(copy, dict) or copy.get("source_rootfs") != "rootfs.squashfs":
        raise InstallerBuilderError("Origen del sistema arrel invàlid")
    if copy.get("verify_sha256") is not True:
        raise InstallerBuilderError("La verificació SHA-256 és obligatòria")
    bootloader = raw.get("bootloader")
    if not isinstance(bootloader, dict) or bootloader.get("type") != "grub-efi-amd64":
        raise InstallerBuilderError("Carregador d'arrencada no suportat")
    if bootloader.get("removable_fallback") is not True:
        raise InstallerBuilderError("El fallback UEFI extraïble és obligatori")
    outputs = raw.get("outputs")
    required_outputs = {"manifest", "installer_config", "installer_script", "summary_schema"}
    if not isinstance(outputs, dict) or set(outputs) != required_outputs:
        raise InstallerBuilderError("outputs de l'instal·lador incomplet")
    raw["outputs"] = {key: _safe_relative(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class InstallerBuildPlan:
    project_root: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.project_root / self.profile["outputs"][key]

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "installer_id": self.profile["installer_id"],
            "product": "XAAC Thin Client OS",
            "architecture": "amd64",
            "hardware_profile": "wyse3040",
            "partition_table": "gpt",
            "minimum_disk_mib": 7168,
            "bootloader": "grub-efi-amd64",
            "destructive_confirmation": "INSTALL XAAC",
            "steps": ["select-disk", "confirm", "partition", "copy", "bootloader", "verify", "summary"],
        }


def create_installer_build_plan(project_root: Path, profile_path: Path) -> InstallerBuildPlan:
    root = project_root.resolve()
    if root == Path("/"):
        raise InstallerBuilderError(f"Arrel de projecte insegura: {root}")
    return InstallerBuildPlan(root, load_installer_builder(profile_path))


class InstallerBuilder:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise InstallerBuilderError(f"Destinació amb enllaç simbòlic: {path}")
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

    def prepare(self, plan: InstallerBuildPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        keys = ("manifest", "installer_config", "installer_script", "summary_schema")
        targets = tuple(plan.output(key) for key in keys)
        if dry_run:
            return targets
        self._write(
            plan.output("manifest"),
            json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            0o644,
        )
        p = plan.profile
        config = {
            "schema_version": 1,
            "confirmation_phrase": p["safety"]["confirmation_phrase"],
            "minimum_disk_mib": p["partition_layout"]["minimum_disk_mib"],
            "partition_table": "gpt",
            "partitions": p["partition_layout"]["partitions"],
            "source_rootfs": p["copy"]["source_rootfs"],
            "source_sha256": p["copy"]["source_sha256"],
            "verify_sha256": True,
            "bootloader": p["bootloader"],
            "post_install": p["post_install"],
        }
        self._write(
            plan.output("installer_config"),
            json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            0o640,
        )
        summary_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["status", "target_disk", "partitions", "bootloader", "verification"],
            "properties": {
                "status": {"enum": ["completed", "failed"]},
                "target_disk": {"type": "string"},
                "partitions": {"type": "array", "minItems": 4},
                "bootloader": {"type": "string"},
                "verification": {"enum": ["passed", "failed"]},
                "error": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        }
        self._write(
            plan.output("summary_schema"),
            json.dumps(summary_schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            0o644,
        )
        script = r'''#!/bin/sh
set -eu
CONFIG=${XAAC_INSTALLER_CONFIG:-/usr/share/xaac-installer/installer.json}
SUMMARY=${XAAC_INSTALLER_SUMMARY:-/var/log/xaac-installer-summary.json}
SOURCE_DIR=${XAAC_INSTALLER_SOURCE:-/run/live/medium/xaac}
TARGET=${1:-}
CONFIRMATION=${2:-}
fail() {
  message=$1
  printf '{"status":"failed","target_disk":"%s","partitions":[],"bootloader":"grub-efi-amd64","verification":"failed","error":"%s"}\n' "$TARGET" "$message" > "$SUMMARY"
  echo "$message" >&2
  exit 1
}
[ "$(id -u)" -eq 0 ] || fail "root privileges required"
[ -b "$TARGET" ] || fail "target is not a block device"
[ "$CONFIRMATION" = "INSTALL XAAC" ] || fail "confirmation phrase rejected"
printf '%s\n' 'Configure the xaac-admin password (minimum 12 characters; colon is not allowed).'
trap 'stty echo 2>/dev/null || true; exit 130' HUP INT TERM
while :; do
  printf '%s' 'Password: '; stty -echo
  IFS= read -r ADMIN_PASSWORD || { stty echo; printf '\n'; fail "password input failed"; }
  stty echo; printf '\n%s' 'Repeat password: '; stty -echo
  IFS= read -r ADMIN_PASSWORD_CONFIRM || { stty echo; printf '\n'; fail "password confirmation failed"; }
  stty echo; printf '\n'
  [ "$ADMIN_PASSWORD" = "$ADMIN_PASSWORD_CONFIRM" ] || { echo 'Passwords do not match.' >&2; continue; }
  [ "${#ADMIN_PASSWORD}" -ge 12 ] || { echo 'Password is too short.' >&2; continue; }
  case "$ADMIN_PASSWORD" in *:*) echo 'Password cannot contain a colon.' >&2; continue ;; esac
  break
done
trap - HUP INT TERM
unset ADMIN_PASSWORD_CONFIRM
case "$TARGET" in /dev/mmcblk*|/dev/sd*|/dev/nvme*n*) ;; *) fail "unsupported target disk" ;; esac
findmnt -rn -S "$TARGET" >/dev/null 2>&1 && fail "target disk is mounted"
ROOT_SOURCE=$(findmnt -nro SOURCE / || true)
case "$ROOT_SOURCE" in "$TARGET"*) fail "refusing running system disk" ;; esac
[ -d /sys/class/power_supply/AC ] || [ -d /sys/class/power_supply/ACAD ] || fail "AC power not detected"
SIZE_MIB=$(blockdev --getsize64 "$TARGET" | awk '{print int($1/1024/1024)}')
[ "$SIZE_MIB" -ge 7168 ] || fail "target disk is too small"
ROOTFS="$SOURCE_DIR/rootfs.squashfs"
ROOTFS_HASH="$SOURCE_DIR/rootfs.squashfs.sha256"
[ -f "$ROOTFS" ] && [ -f "$ROOTFS_HASH" ] || fail "installation source is incomplete"
(cd "$SOURCE_DIR" && sha256sum -c rootfs.squashfs.sha256) || fail "rootfs checksum failed"
sgdisk --zap-all "$TARGET"
sgdisk -n 1:1MiB:+256MiB -t 1:ef00 -c 1:XAAC_EFI "$TARGET"
sgdisk -n 2:0:+4096MiB -t 2:8300 -c 2:XAAC_ROOT "$TARGET"
sgdisk -n 3:0:+1024MiB -t 3:8300 -c 3:XAAC_DATA "$TARGET"
sgdisk -n 4:0:0 -t 4:8300 -c 4:XAAC_RECOVERY "$TARGET"
partprobe "$TARGET"; udevadm settle
case "$TARGET" in /dev/mmcblk*|/dev/nvme*) P=${TARGET}p ;; *) P=$TARGET ;; esac
mkfs.vfat -F 32 -n XAAC_EFI "${P}1"
mkfs.ext4 -F -L XAAC_ROOT "${P}2"
mkfs.ext4 -F -L XAAC_DATA "${P}3"
mkfs.ext4 -F -L XAAC_RECOVERY "${P}4"
WORK=$(mktemp -d); trap 'umount "$WORK/root/boot/efi" "$WORK/root" 2>/dev/null || true; rm -rf "$WORK"' EXIT
mkdir -p "$WORK/root"; mount "${P}2" "$WORK/root"
unsquashfs -f -d "$WORK/root" "$ROOTFS"
KERNEL_VERSION=$(find "$WORK/root/lib/modules" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V | tail -n1)
[ -n "$KERNEL_VERSION" ] || fail "installed kernel version could not be determined"
[ -s "$SOURCE_DIR/vmlinuz" ] && [ -s "$SOURCE_DIR/initrd.img" ] || fail "kernel or initramfs is missing from installation source"
mkdir -p "$WORK/root/boot"
install -m 0644 "$SOURCE_DIR/vmlinuz" "$WORK/root/boot/vmlinuz-$KERNEL_VERSION"
install -m 0644 "$SOURCE_DIR/initrd.img" "$WORK/root/boot/initrd.img-$KERNEL_VERSION"
ln -sfn "vmlinuz-$KERNEL_VERSION" "$WORK/root/boot/vmlinuz"
ln -sfn "initrd.img-$KERNEL_VERSION" "$WORK/root/boot/initrd.img"
mkdir -p "$WORK/root/boot/efi"; mount "${P}1" "$WORK/root/boot/efi"
ROOT_UUID=$(blkid -s UUID -o value "${P}2")
[ -n "$ROOT_UUID" ] || fail "root filesystem UUID could not be determined"
mount --bind /dev "$WORK/root/dev"; mount -t proc proc "$WORK/root/proc"; mount -t sysfs sys "$WORK/root/sys"
mkdir -p "$WORK/root/etc/default/grub.d" "$WORK/root/etc/grub.d"
cat > "$WORK/root/etc/default/grub.d/10-xaac-identity.cfg" <<'EOF'
GRUB_DISTRIBUTOR="XAAC Thin Client OS"
GRUB_DISABLE_SUBMENU=y
EOF
cat > "$WORK/root/etc/grub.d/09_xaac" <<EOF
#!/bin/sh
cat <<'XAAC_ENTRY'
menuentry 'XAAC Thin Client OS' --class xaac --class gnu-linux --class gnu --class os {
    insmod part_gpt
    insmod ext2
    search --no-floppy --fs-uuid --set=root $ROOT_UUID
    linux /boot/vmlinuz root=UUID=$ROOT_UUID ro quiet
    initrd /boot/initrd.img
}
XAAC_ENTRY
EOF
chmod 0755 "$WORK/root/etc/grub.d/09_xaac"
chmod -x "$WORK/root/etc/grub.d/10_linux"
chroot "$WORK/root" grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=XAAC --removable --no-nvram
chroot "$WORK/root" update-grub
[ -s "$WORK/root/boot/grub/grub.cfg" ] || fail "grub.cfg was not generated"
grep -Fq "menuentry 'XAAC Thin Client OS'" "$WORK/root/boot/grub/grub.cfg" || fail "grub.cfg has no XAAC Thin Client OS menuentry"
grep -Eq '^[[:space:]]*linux[[:space:]]+.*vmlinuz' "$WORK/root/boot/grub/grub.cfg" || fail "grub.cfg has no linux kernel command"
grep -Eq '^[[:space:]]*initrd[[:space:]]+.*initrd' "$WORK/root/boot/grub/grub.cfg" || fail "grub.cfg has no initrd command"
ADMIN_HASH=$(printf '%s' "$ADMIN_PASSWORD" | openssl passwd -6 -stdin)
case "$ADMIN_HASH" in '$6$'*) ;; *) fail "xaac-admin SHA-512 password hash generation failed" ;; esac
chroot "$WORK/root" usermod --password "$ADMIN_HASH" --unlock --shell /bin/bash xaac-admin
chroot "$WORK/root" chage -E -1 -I -1 -m 0 xaac-admin
[ "$(chroot "$WORK/root" passwd -S xaac-admin | awk '{print $2}')" = P ] || fail "xaac-admin password activation failed"
SHADOW_PASSWORD=$(chroot "$WORK/root" getent shadow xaac-admin | cut -d: -f2)
case "$SHADOW_PASSWORD" in ''|\!*|\**) fail "xaac-admin remains locked in shadow" ;; esac
[ "$(chroot "$WORK/root" getent passwd xaac-admin | cut -d: -f7)" = /bin/bash ] || fail "xaac-admin shell is not interactive"
printf '%s\n' "$ADMIN_PASSWORD" | chroot "$WORK/root" pamtester login xaac-admin authenticate >/dev/null 2>&1 || fail "PAM rejected xaac-admin password"
chroot "$WORK/root" mkdir -p /var/lib/xaac/admin
chroot "$WORK/root" install -o root -g xaac-admin -m 0640 /dev/null /var/lib/xaac/admin/password-changed
unset ADMIN_PASSWORD
umount "$WORK/root/sys" "$WORK/root/proc" "$WORK/root/dev"
touch "$WORK/root/etc/xaac-first-boot.pending"
sync
printf '{"status":"completed","target_disk":"%s","partitions":["XAAC_EFI","XAAC_ROOT","XAAC_DATA","XAAC_RECOVERY"],"bootloader":"grub-efi-amd64","verification":"passed","error":null}\n' "$TARGET" > "$SUMMARY"
echo "XAAC Thin Client OS installation completed on $TARGET"
'''
        self._write(plan.output("installer_script"), script, 0o750)
        return targets
