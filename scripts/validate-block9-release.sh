#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}

case "$PYTHON" in
    */*)
        if [ ! -x "$PYTHON" ]; then
            printf 'Error: no existeix %s. Executa scripts/create-venv.sh.\n' "$PYTHON" >&2
            exit 1
        fi
        ;;
    *)
        PYTHON=$(command -v "$PYTHON" 2>/dev/null || true)
        if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
            printf "Error: no s'ha trobat l'intèrpret Python sol·licitat.\n" >&2
            exit 1
        fi
        ;;
esac

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

printf '%s\n' '[XAAC] Gate final Bloc 9: integració, visual, hardening i regressió completa.'
"$PROJECT_ROOT/scripts/validate-block7-release.sh"
"$PROJECT_ROOT/scripts/validate-block7-integration.sh"
"$PROJECT_ROOT/scripts/validate-block8-visual.sh"
"$PROJECT_ROOT/scripts/validate-block9-hardening.sh"
"$PYTHON" -m pytest -q

command -v dpkg-deb >/dev/null 2>&1 || {
    printf '%s\n' 'Error: dpkg-deb és necessari per validar els paquets de producció.' >&2
    exit 2
}

for artifact in \
    packages/xaac-agent_1.0.0-8_amd64.deb \
    packages/xaac-thin-client-vpn_1.0.0_all.deb \
    packages/xaac-thinclient_1.0.0_all.deb
do
    if [ ! -f "$artifact" ] || ! dpkg-deb --info "$artifact" >/dev/null 2>&1; then
        printf 'Error: artefacte de producció absent o invàlid: %s\n' "$artifact" >&2
        exit 3
    fi
done

printf '%s\n' 'Bloc 9.4 pre-ISO: gate tècnic superat per l’abast integrat actual.'
