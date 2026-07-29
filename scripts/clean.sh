#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

find . -type d -name '__pycache__' -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist .build
find . -maxdepth 2 -type d -name '*.egg-info' -prune -exec rm -rf {} +
