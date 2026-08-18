#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

PYTHON=${PYTHON:-python3}
if [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
fi

"$PYTHON" -m pytest -q \
    tests/test_block10_phase4.py \
    tests/test_recovery_environment_phase10.py \
    tests/test_recovery_runtime_phase10.py \
    tests/test_update_runtime_configuration_restore.py \
    tests/test_update_transaction_runtime.py \
    tests/test_update_admin_runtime.py \
    tests/test_package_rollback.py \
    tests/test_maintenance_runtime.py \
    tests/test_maintenance_diagnostics.py
