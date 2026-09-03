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
printf '%s\n' '[XAAC] Validació Fase 10.6: actualització controlada del sistema base Debian 13.'

"$PYTHON" -m py_compile \
    src/xaac_thin_client_os/base_os_update.py \
    assets/runtime/xaac-update-admin \
    assets/runtime/xaac_base_os_update_runtime.py

"$PYTHON" -m pytest -q \
    tests/test_base_os_update.py \
    tests/test_base_os_update_runtime.py \
    tests/test_block10_phase6.py \
    tests/test_update_admin_runtime.py \
    tests/test_local_admin.py \
    tests/test_production_builder.py \
    tests/test_recovery_runtime_phase10.py

printf '%s\n' 'Fase 10.6 superada a nivell de codi. Cal validar os-check/os-update en una ISO candidata abans de producció.'
