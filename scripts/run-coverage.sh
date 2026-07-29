#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    printf 'Error: no existeix %s. Executa scripts/create-venv.sh.\n' "$PYTHON" >&2
    exit 1
fi

exec "$PYTHON" -m pytest \
    --cov=xaac_thin_client_os \
    --cov-report=term-missing \
    --cov-report=html \
    "$@"
