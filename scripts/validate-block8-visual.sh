#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}

if [ ! -x "$PYTHON" ]; then
    printf 'Error: no existeix %s. Executa scripts/create-venv.sh.\n' "$PYTHON" >&2
    exit 1
fi

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" -m pytest -q \
    tests/test_production_builder.py::test_production_builder_uses_one_appliance_kernel_policy_for_live_and_installed_boot \
    tests/test_production_builder.py::test_production_boot_and_shutdown_use_xaac_plymouth_branding \
    tests/test_production_builder.py::test_production_iso_hides_grub_menu_and_uses_appliance_boot_parameters \
    tests/test_session_supervisor.py::test_startup_screen_is_fullscreen_and_bounded \
    tests/test_block8_visual_handoff.py \
    tests/test_tty_cursor_visibility.py

printf '%s\n' 'Bloc 8.2: validació visual estàtica superada.'
