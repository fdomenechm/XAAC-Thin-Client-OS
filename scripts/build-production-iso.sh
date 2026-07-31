#!/usr/bin/env bash
set -Eeuo pipefail

# Debian minimal and non-login SSH sessions may omit administrative paths.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
    printf 'Error: no existeix %s. Executa scripts/create-venv.sh.\n' "$PYTHON" >&2
    exit 1
fi

for command in debootstrap mksquashfs grub-mkrescue xorriso sha256sum mount umount chroot; do
    command -v "$command" >/dev/null 2>&1 || {
        printf 'Error: falta la dependència del sistema: %s\n' "$command" >&2
        printf 'Executa: sudo ./scripts/install-build-dependencies.sh\n' >&2
        exit 2
    }
done

if [[ ${EUID} -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || {
        printf 'Error: la construcció requereix root o sudo.\n' >&2
        exit 3
    }
    exec sudo --preserve-env=PYTHON "$0" "$@"
fi

cd "$PROJECT_ROOT"
exec "$PYTHON" -m xaac_thin_client_os.production_builder --root "$PROJECT_ROOT" "$@"
