#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}

case "$PYTHON" in
    */*)
        if [ ! -x "$PYTHON" ]; then
            PYTHON=$(command -v python3 2>/dev/null || true)
        fi
        ;;
    *)
        PYTHON=$(command -v "$PYTHON" 2>/dev/null || true)
        ;;
esac

if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    printf '%s\n' "Error: no s'ha trobat Python 3." >&2
    exit 1
fi

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

printf '%s\n' '[XAAC] Validació Fase 10.1: arquitectura, manifest, preflight i integració de producció.'
"$PYTHON" -m pytest -q \
    tests/test_update_model.py \
    tests/test_update_release_manifest.py \
    tests/test_update_admin_runtime.py \
    tests/test_production_builder.py

"$PYTHON" -m xaac_thin_client_os \
    --root "$PROJECT_ROOT" \
    create-update-manifest \
    --output .build/artifacts/xaac-update-manifest.phase10-1.json >/dev/null

[ -s .build/artifacts/xaac-update-manifest.phase10-1.json ] || {
    printf '%s\n' 'Error: no s’ha generat el manifest de prova de la Fase 10.1.' >&2
    exit 2
}
rm -f .build/artifacts/xaac-update-manifest.phase10-1.json

printf '%s\n' 'Fase 10.1 superada. No cal generar ISO en aquesta fase.'
