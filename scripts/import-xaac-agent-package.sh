#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ARTIFACT=${1:-}

if [ -z "$ARTIFACT" ]; then
    printf 'Ús: %s /ruta/al/xaac-agent_VERSION_amd64.deb\n' "$0" >&2
    exit 2
fi

PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}
if [ ! -x "$PYTHON" ]; then
    printf 'Error: falta %s. Executa scripts/create-venv.sh.\n' "$PYTHON" >&2
    exit 2
fi

case "$ARTIFACT" in
    /*) ;;
    *) ARTIFACT=$(CDPATH= cd -- "$(dirname -- "$ARTIFACT")" && pwd)/$(basename -- "$ARTIFACT") ;;
esac

[ -f "$ARTIFACT" ] || {
    printf 'Error: no existeix el paquet: %s\n' "$ARTIFACT" >&2
    exit 2
}
[ -f "$ARTIFACT.provenance.json" ] || {
    printf 'Error: falta la provenança adjacent: %s.provenance.json\n' "$ARTIFACT" >&2
    exit 2
}

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" - "$PROJECT_ROOT" "$ARTIFACT" <<'PY'
import json
import sys
from pathlib import Path

from xaac_thin_client_os.agent_release_import import AgentReleaseImportError, import_agent_release

try:
    result = import_agent_release(Path(sys.argv[1]), Path(sys.argv[2]))
except AgentReleaseImportError as exc:
    print(json.dumps({"schema": "xaac-agent-release-import/v1", "imported": False, "error": str(exc)}, sort_keys=True))
    raise SystemExit(1)
print(json.dumps(result.to_payload(), sort_keys=True))
PY

printf '[XAAC] Paquet canònic incorporat. Ja pots construir la ISO amb:\n'
printf '  ./scripts/build-production-iso.sh --clean\n'
