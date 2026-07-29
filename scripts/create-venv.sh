#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3.13}"
VENV_DIR="${VENV_DIR:-.venv}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    printf 'Error: no s’ha trobat %s. Instal·la Python 3.13 o defineix PYTHON_BIN.\n' "$PYTHON_BIN" >&2
    exit 1
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)' || {
    printf 'Error: XAAC Thin Client OS requereix Python 3.13.\n' >&2
    exit 1
}

if [[ -e "$VENV_DIR" && ! -x "$VENV_DIR/bin/python" ]]; then
    printf 'Error: %s existeix però no és un entorn virtual vàlid.\n' "$VENV_DIR" >&2
    exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -e '.[dev]'
printf 'Entorn preparat: %s/%s\n' "$PROJECT_ROOT" "$VENV_DIR"
