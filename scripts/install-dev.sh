#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON="$VENV_DIR/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    printf 'Error: no existeix %s. Executa primer scripts/create-venv.sh.\n' "$PYTHON" >&2
    exit 1
fi

"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -e '.[dev]'
