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

from xaac_thin_client_os.block7_release import Block7ReleaseError, validate_block7_release_provenance

try:
    result = validate_block7_release_provenance(Path(sys.argv[1]), require_canonical=True)
except Block7ReleaseError as exc:
    print(json.dumps({"schema": "xaac-block7-release-gate/v1", "passed": False, "error": str(exc)}, sort_keys=True))
    raise SystemExit(1)
payload = result.to_payload()
payload["schema"] = "xaac-block7-release-gate/v1"
payload["passed"] = True
print(json.dumps(payload, sort_keys=True))
PY
