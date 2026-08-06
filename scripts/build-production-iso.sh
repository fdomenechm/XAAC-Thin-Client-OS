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

for command in debootstrap mksquashfs grub-mkrescue xorriso sha256sum mount umount chroot sync unshare; do
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

# Run the complete build in a private mount namespace. This prevents mount
# propagation to the host and guarantees that any residual chroot mounts
# disappear when the namespace terminates, even after an abnormal exit.
if [[ ${XAAC_PRIVATE_MOUNT_NS:-0} != 1 ]]; then
    export XAAC_PRIVATE_MOUNT_NS=1
    exec unshare --mount --propagation private -- "$0" "$@"
fi

cd "$PROJECT_ROOT"

cleanup_chroot_mounts() {
    "$PYTHON" -m xaac_thin_client_os.production_builder \
        --root "$PROJECT_ROOT" --cleanup-mounts-only
}

cleanup_on_exit() {
    local status=$?
    trap - EXIT INT TERM
    cleanup_chroot_mounts || {
        printf 'Error: la neteja segura del chroot no ha finalitzat correctament.\n' >&2
        [[ $status -ne 0 ]] || status=1
    }
    exit "$status"
}

cleanup_on_signal() {
    local signal=$1
    trap - EXIT INT TERM
    cleanup_chroot_mounts || true
    kill -s "$signal" "$$"
}

# Preserve the original exit status, handle signals explicitly, and ensure the
# cleanup routine remains strictly scoped below .build/production/rootfs.
trap cleanup_on_exit EXIT
trap 'cleanup_on_signal INT' INT
trap 'cleanup_on_signal TERM' TERM

"$PYTHON" -m xaac_thin_client_os.production_builder --root "$PROJECT_ROOT" "$@"
