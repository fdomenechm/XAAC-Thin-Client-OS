#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}

case "$PYTHON" in
    */*) [ -x "$PYTHON" ] || PYTHON=$(command -v python3 2>/dev/null || true) ;;
    *) PYTHON=$(command -v "$PYTHON" 2>/dev/null || true) ;;
esac
if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    printf '%s\n' "Error: no s'ha trobat Python 3." >&2
    exit 1
fi

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
printf '%s\n' '[XAAC] Validació Fase 10.3: manteniment, diagnòstic sanititzat i integració administrativa.'

"$PYTHON" -m py_compile \
    assets/runtime/xaac-maintenance \
    assets/runtime/xaac_maintenance_runtime.py \
    src/xaac_thin_client_os/maintenance_diagnostics.py
"$PYTHON" -m pytest -q \
    tests/test_maintenance_diagnostics.py \
    tests/test_maintenance_runtime.py \
    tests/test_block10_phase3.py \
    tests/test_local_admin.py \
    tests/test_production_builder.py \
    tests/test_block10_phase2.py

printf '%s\n' 'Fase 10.3 superada. No cal generar ISO en aquesta fase.'
