#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -eq 0 ]]; then
    APT=(apt-get)
else
    if ! command -v sudo >/dev/null 2>&1; then
        printf 'Error: cal executar com a root o disposar de sudo.\n' >&2
        exit 1
    fi
    APT=(sudo apt-get)
fi

if ! command -v apt-get >/dev/null 2>&1; then
    printf 'Error: aquest script requereix un sistema Debian o derivat amb apt-get.\n' >&2
    exit 1
fi

"${APT[@]}" update
"${APT[@]}" install --yes --no-install-recommends \
    debootstrap \
    debian-archive-keyring \
    gdisk \
    parted \
    dosfstools \
    e2fsprogs \
    rsync \
    grub-efi-amd64-bin \
    grub2-common \
    grub-pc-bin \
    xorriso \
    squashfs-tools \
    util-linux \
    coreutils

printf 'Dependències del constructor instal·lades correctament.\n'
