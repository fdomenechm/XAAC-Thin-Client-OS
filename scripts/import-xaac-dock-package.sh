#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ARTIFACT=${1:-}

if [ -z "$ARTIFACT" ]; then
    printf 'Ús: %s %s\n' "$0" '/ruta/al/xaac-thin-client-dock_VERSION_all.deb' >&2
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

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" - "$PROJECT_ROOT" "$ARTIFACT" <<'PY'
import json
import sys
from pathlib import Path

from xaac_thin_client_os.component_release_import import (
    ComponentReleaseImportError,
    import_component_release,
)

try:
    result = import_component_release(Path(sys.argv[1]), Path(sys.argv[2]), component="dock")
except ComponentReleaseImportError as exc:
    print(json.dumps({"schema": "xaac-component-release-import/v1", "imported": False, "component": "dock", "error": str(exc)}, sort_keys=True))
    raise SystemExit(1)
print(json.dumps(result.to_payload(), sort_keys=True))
PY

printf '[XAAC] Paquet %s incorporat i perfil sincronitzat.\n' 'dock'
printf '[XAAC] Executa ./scripts/run-tests.sh abans de construir la ISO.\n'
