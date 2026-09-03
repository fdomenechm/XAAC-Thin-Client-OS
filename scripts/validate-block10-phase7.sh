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
printf '%s\n' "[XAAC] Validació Fase 10.7: selecció d'idioma i teclat de l'instal·lador."

"$PYTHON" -m py_compile src/xaac_thin_client_os/production_builder.py
"$PYTHON" -m pytest -q \
    tests/test_production_builder.py \
    tests/test_localization.py \
    tests/test_system_configuration.py

printf '%s\n' 'Fase 10.7 superada a nivell de codi. La persistència real es validarà en la primera instal·lació física del Bloc 11.'
