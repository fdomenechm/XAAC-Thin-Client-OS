#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}
CHANNEL=${1:-production}
KEY=${XAAC_RELEASE_SIGNING_KEY:-}
OUTPUT=${XAAC_UPDATE_BUNDLE_DIR:-"$PROJECT_ROOT/.build/artifacts/update-bundle"}

case "$PYTHON" in
    */*) [ -x "$PYTHON" ] || PYTHON=$(command -v python3 2>/dev/null || true) ;;
    *) PYTHON=$(command -v "$PYTHON" 2>/dev/null || true) ;;
esac
if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    printf '%s\n' 'Error: no s’ha trobat Python 3.' >&2
    exit 1
fi
if [ -z "$KEY" ]; then
    printf '%s\n' 'Error: defineix XAAC_RELEASE_SIGNING_KEY amb el fingerprint de la clau privada de release.' >&2
    exit 64
fi
GPG=$(command -v gpg 2>/dev/null || true)
if [ -z "$GPG" ]; then
    printf '%s\n' 'Error: gpg no està instal·lat a la màquina de release.' >&2
    exit 1
fi

rm -rf "$OUTPUT"
mkdir -p "$OUTPUT"
MANIFEST="$OUTPUT/update-manifest.json"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON" -m xaac_thin_client_os --root "$PROJECT_ROOT" create-update-manifest \
    --channel "$CHANNEL" --output "${MANIFEST#$PROJECT_ROOT/}" >/dev/null

"$PYTHON" - "$MANIFEST" "$PROJECT_ROOT/packages" "$OUTPUT" <<'PY'
import json
import shutil
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
packages = Path(sys.argv[2])
output = Path(sys.argv[3])
data = json.loads(manifest.read_text(encoding="utf-8"))
for component in data["components"]:
    name = component["filename"]
    if Path(name).name != name:
        raise SystemExit(f"nom d'artefacte insegur: {name}")
    source = packages / name
    if not source.is_file():
        raise SystemExit(f"falta el paquet: {source}")
    shutil.copy2(source, output / name)
PY

"$GPG" --batch --yes --armor --detach-sign --local-user "$KEY" \
    --output "$MANIFEST.asc" "$MANIFEST"
[ -s "$MANIFEST.asc" ] || { printf '%s\n' 'Error: no s’ha generat la signatura.' >&2; exit 2; }
printf 'Bundle signat generat: %s\n' "$OUTPUT"
