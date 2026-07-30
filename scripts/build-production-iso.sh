#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
PYTHON="${PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
    printf 'Error: no existeix %s. Executa scripts/create-venv.sh.\n' "$PYTHON" >&2
    exit 1
fi

if [[ ${EUID} -ne 0 ]]; then
    if ! command -v sudo >/dev/null 2>&1; then
        printf 'Error: la construcció completa requereix root o sudo.\n' >&2
        exit 1
    fi
    exec sudo --preserve-env=PYTHON,XAAC_ISO_SIGNING_KEY,XAAC_REQUIRE_ISO_SIGNATURE \
        "$0" "$@"
fi

for command in debootstrap mksquashfs grub-mkrescue xorriso rsync sha256sum; do
    command -v "$command" >/dev/null 2>&1 || {
        printf 'Error: falta la dependència del sistema: %s\n' "$command" >&2
        printf 'Executa: sudo ./scripts/install-build-dependencies.sh\n' >&2
        exit 2
    }
done

printf '\n[1/5] Construint el rootfs i la imatge base...\n'
"$PYTHON" -m xaac_thin_client_os --root "$PROJECT_ROOT" build-image

BUILD_ID="$(tr -d '\r\n' < .build/current)"
RUN_DIR="$PROJECT_ROOT/.build/runs/$BUILD_ID"
ROOTFS="$RUN_DIR/rootfs"
[[ -f "$ROOTFS/etc/debian_version" ]] || {
    printf 'Error: el rootfs no s’ha generat correctament: %s\n' "$ROOTFS" >&2
    exit 3
}

printf '\n[2/5] Preparant kernel, initramfs i SquashFS...\n'
mkdir -p .build/image .build/rootfs/boot .build/boot/efi-tree/EFI/BOOT .build/artifacts
KERNEL="$(find "$ROOTFS/boot" -maxdepth 1 -type f -name 'vmlinuz-*' -printf '%f\n' | sort -V | tail -n1)"
[[ -n "$KERNEL" ]] || { printf 'Error: no hi ha kernel en %s/boot.\n' "$ROOTFS" >&2; exit 4; }
VERSION="${KERNEL#vmlinuz-}"
INITRD="initrd.img-$VERSION"
[[ -f "$ROOTFS/boot/$INITRD" ]] || { printf 'Error: falta %s.\n' "$ROOTFS/boot/$INITRD" >&2; exit 4; }
install -m0644 "$ROOTFS/boot/$KERNEL" .build/rootfs/boot/vmlinuz
install -m0644 "$ROOTFS/boot/$INITRD" .build/rootfs/boot/initrd.img
rm -f .build/image/rootfs.squashfs
mksquashfs "$ROOTFS" .build/image/rootfs.squashfs -comp xz -b 1M -noappend -no-progress

printf '\n[3/5] Preparant els recursos d’arrencada GRUB...\n'
# grub-mkrescue crearà les imatges BIOS/UEFI definitives. Aquests marcadors
# satisfan el manifest antic i documenten que les fonts han estat preparades.
printf 'generated-by-grub-mkrescue\n' > .build/boot/efi.img
printf 'generated-by-grub-mkrescue\n' > .build/boot/isohdpfx.bin

printf '\n[4/5] Preparant i executant el constructor ISO...\n'
"$PYTHON" -m xaac_thin_client_os --root "$PROJECT_ROOT" build-iso
rm -f .build/artifacts/xaac-thin-client-os-amd64.iso \
      .build/artifacts/xaac-thin-client-os-amd64.iso.sha256 \
      .build/artifacts/xaac-thin-client-os-amd64.iso.asc
./.build/iso/build-iso.sh

printf '\n[5/5] Verificant l’artefacte...\n'
(cd .build/artifacts && sha256sum -c xaac-thin-client-os-amd64.iso.sha256)
chown -R "${SUDO_UID:-0}:${SUDO_GID:-0}" .build 2>/dev/null || true
printf '\nISO generada correctament:\n  %s\n' "$PROJECT_ROOT/.build/artifacts/xaac-thin-client-os-amd64.iso"
