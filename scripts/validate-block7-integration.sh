#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi

exec "$PYTHON" - "$PROJECT_ROOT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

from xaac_thin_client_os.block7_integration import (
    Block7IntegrationError,
    validate_packaged_block7_integration,
)

try:
    report = validate_packaged_block7_integration(Path(sys.argv[1]))
except Block7IntegrationError as exc:
    print(json.dumps({"schema": "xaac-block7-integration-report/v1", "passed": False, "error": str(exc)}, sort_keys=True))
    raise SystemExit(1)
print(json.dumps(report.to_payload(), sort_keys=True))
PY
