#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FINGERPRINT=${1:-}

if [ -z "$FINGERPRINT" ]; then
    printf '%s\n' 'Ús: ./scripts/provision-update-keyring.sh FINGERPRINT' >&2
    exit 64
fi
GPG=$(command -v gpg 2>/dev/null || true)
if [ -z "$GPG" ]; then
    printf '%s\n' 'Error: gpg no està instal·lat a la màquina de release.' >&2
    exit 1
fi

TARGET="$PROJECT_ROOT/assets/release/xaac-archive-keyring.gpg"
TMP="$TARGET.tmp.$$"
trap 'rm -f "$TMP"' EXIT HUP INT TERM
mkdir -p "$(dirname -- "$TARGET")"
"$GPG" --batch --export "$FINGERPRINT" > "$TMP"
if [ ! -s "$TMP" ]; then
    printf '%s\n' 'Error: no s’ha pogut exportar la clau pública indicada.' >&2
    exit 2
fi
chmod 0644 "$TMP"
mv -f "$TMP" "$TARGET"
trap - EXIT HUP INT TERM
printf 'Keyring públic provisionat: %s\n' "$TARGET"
