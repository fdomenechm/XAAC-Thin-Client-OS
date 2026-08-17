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
printf '%s\n' '[XAAC] Validació Fase 10.2: transacció, health-check, rollback i integració de producció.'

sh -n scripts/provision-update-keyring.sh
sh -n scripts/build-update-bundle.sh
"$PYTHON" -m py_compile assets/runtime/xaac-update-admin assets/runtime/xaac_update_runtime.py
"$PYTHON" -m pytest -q \
    tests/test_update_model.py \
    tests/test_update_release_manifest.py \
    tests/test_transactional_update.py \
    tests/test_package_rollback.py \
    tests/test_update_admin_runtime.py \
    tests/test_update_transaction_runtime.py \
    tests/test_block10_phase2.py \
    tests/test_production_builder.py

printf '%s\n' 'Fase 10.2 superada. No cal generar ISO en aquesta fase.'
