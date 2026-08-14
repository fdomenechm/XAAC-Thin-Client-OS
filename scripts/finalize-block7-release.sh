#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
AGENT_SOURCE=${1:-}

if [ -z "$AGENT_SOURCE" ]; then
    printf 'Ús: %s /ruta/al/xaac-agent\n' "$0" >&2
    exit 2
fi
AGENT_SOURCE=$(CDPATH= cd -- "$AGENT_SOURCE" && pwd)

[ -x "$AGENT_SOURCE/scripts/build-debian-release.sh" ] || {
    printf 'Error: el projecte Agent no conté scripts/build-debian-release.sh.\n' >&2
    exit 2
}
[ -x "$PROJECT_ROOT/.venv/bin/python" ] || {
    printf 'Error: falta %s/.venv. Executa scripts/create-venv.sh.\n' "$PROJECT_ROOT" >&2
    exit 2
}

WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/xaac-block7-final.XXXXXX")
cleanup() { rm -rf -- "$WORKDIR"; }
trap cleanup EXIT HUP INT TERM

ARTIFACTS="$WORKDIR/artifacts"
mkdir -p "$ARTIFACTS"

printf '[XAAC] Construint canònicament XAAC Agent...\n'
"$AGENT_SOURCE/scripts/build-debian-release.sh" "$ARTIFACTS"

VERSION=$(dpkg-parsechangelog -l"$AGENT_SOURCE/debian/changelog" -SVersion)
ARCH=$(dpkg-architecture -qDEB_HOST_ARCH)
DEB="$ARTIFACTS/xaac-agent_${VERSION}_${ARCH}.deb"
PROVENANCE="$DEB.provenance.json"
[ -f "$DEB" ] && [ -f "$PROVENANCE" ] || {
    printf 'Error: la construcció canònica no ha generat artefacte i provenança.\n' >&2
    exit 3
}

SHA256=$(sha256sum "$DEB" | awk '{print $1}')
PACKAGE_DIR="$PROJECT_ROOT/packages"
DEST="$PACKAGE_DIR/$(basename "$DEB")"
DEST_PROVENANCE="$DEST.provenance.json"
mkdir -p "$PACKAGE_DIR"
find "$PACKAGE_DIR" -maxdepth 1 -type f \( -name 'xaac-agent_*.deb' -o -name 'xaac-agent_*.deb.provenance.json' \) -delete
cp -- "$DEB" "$DEST"
cp -- "$PROVENANCE" "$DEST_PROVENANCE"

printf '[XAAC] Actualitzant el perfil de paquet amb el SHA-256 canònic...\n'
"$PROJECT_ROOT/.venv/bin/python" - "$PROJECT_ROOT/config/xaac-agent-package.yaml" "$VERSION" "packages/$(basename "$DEB")" "$SHA256" <<'PY'
import sys
from pathlib import Path
import yaml
path = Path(sys.argv[1])
payload = yaml.safe_load(path.read_text(encoding="utf-8"))
payload["package"]["version"] = sys.argv[2]
payload["package"]["artifact"] = sys.argv[3]
payload["package"]["sha256"] = sys.argv[4]
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
tmp.replace(path)
PY

printf '[XAAC] Validant provenança, contracte Bloc 7 i suites...\n'
"$PROJECT_ROOT/scripts/validate-block7-release.sh"
"$PROJECT_ROOT/scripts/validate-block7-integration.sh"
(
    cd "$AGENT_SOURCE"
    PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3.13 -m pytest -q
)
(
    cd "$PROJECT_ROOT"
    PYTHONDONTWRITEBYTECODE=1 "$PROJECT_ROOT/.venv/bin/python" -m pytest -q
)

printf '[XAAC] Generant l’única ISO consolidada del Bloc 7...\n'
exec "$PROJECT_ROOT/scripts/build-production-iso.sh" --clean
