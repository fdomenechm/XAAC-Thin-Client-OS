#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}

case "$PYTHON" in
    */*)
        if [ ! -x "$PYTHON" ]; then
            printf 'Error: no existeix %s. Executa scripts/create-venv.sh.\n' "$PYTHON" >&2
            exit 1
        fi
        ;;
    *)
        PYTHON=$(command -v "$PYTHON" 2>/dev/null || true)
        if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
            printf "Error: no s'ha trobat l'intèrpret Python sol·licitat.\n" >&2
            exit 1
        fi
        ;;
esac

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" -m pytest -q \
    tests/test_block9_hardening.py \
    tests/test_kernel_hardening.py \
    tests/test_resource_optimization.py \
    tests/test_ssh_configuration.py \
    tests/test_firewall_configuration.py \
    tests/test_production_installer_ssh_hostkeys.py \
    tests/test_production_builder.py

printf '%s\n' "Bloc 9.2: kernel, recursos i eMMC validats; no cal generar ISO encara."
