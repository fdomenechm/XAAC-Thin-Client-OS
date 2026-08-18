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
printf '%s\n' '[XAAC] Validació Fase 10.5: fallades controlades, gate final i qualificació física.'

sh -n assets/runtime/xaac-block10-validate
"$PYTHON" -m pytest -q \
    tests/test_block10_phase5.py \
    tests/test_block10_failure_matrix.py \
    tests/test_update_admin_runtime.py \
    tests/test_update_transaction_runtime.py \
    tests/test_update_runtime_configuration_restore.py \
    tests/test_recovery_runtime_phase10.py \
    tests/test_maintenance_runtime.py \
    tests/test_maintenance_diagnostics.py \
    tests/test_production_builder.py

printf '%s\n' 'Fase 10.5 superada a nivell de codi. La qualificació física continua requerida al Wyse 3040.'
