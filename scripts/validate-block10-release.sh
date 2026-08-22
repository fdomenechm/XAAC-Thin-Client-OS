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
            printf "%s\n" "Error: no s'ha trobat l'intèrpret Python sol·licitat." >&2
            exit 1
        fi
        ;;
esac

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

printf '%s\n' '[XAAC] Gate final Bloc 10: regressió completa i comprovacions de release.'

# Run the complete suite exactly once.  The phase gates below are deliberately
# not re-executed because they are pytest subsets of this same suite; repeating
# them only increases release time and has no additional coverage.
"$PYTHON" -m pytest -q

# Block 7 has two canonical release checks that inspect the actual packaged
# artifact/provenance rather than merely selecting pytest cases, so keep them as
# explicit release operations.
"$PROJECT_ROOT/scripts/validate-block7-release.sh"
"$PROJECT_ROOT/scripts/validate-block7-integration.sh"

# Keep every historical/focused gate executable and syntactically valid.  Their
# test cases have already passed above in the complete regression.
for gate in \
    scripts/validate-block8-visual.sh \
    scripts/validate-block9-hardening.sh \
    scripts/validate-block10-phase1.sh \
    scripts/validate-block10-phase2.sh \
    scripts/validate-block10-phase3.sh \
    scripts/validate-block10-phase4.sh \
    scripts/validate-block10-phase5.sh \
    scripts/validate-block10-phase6.sh \
    scripts/validate-block10-phase7.sh
do
    if [ ! -x "$gate" ]; then
        printf 'Error: gate absent o no executable: %s\n' "$gate" >&2
        exit 2
    fi
    sh -n "$gate"
done

sh -n assets/runtime/xaac-block9-validate
sh -n assets/runtime/xaac-block10-validate
"$PYTHON" -m py_compile \
    assets/runtime/xaac-update-admin \
    assets/runtime/xaac_update_runtime.py \
    assets/runtime/xaac_base_os_update_runtime.py \
    assets/runtime/xaac-maintenance \
    assets/runtime/xaac_maintenance_runtime.py \
    assets/runtime/xaac-recovery \
    assets/runtime/xaac_recovery_runtime.py

command -v dpkg-deb >/dev/null 2>&1 || {
    printf '%s\n' 'Error: dpkg-deb és necessari per validar els paquets de producció.' >&2
    exit 3
}

for artifact in \
    packages/xaac-agent_1.0.0-8_amd64.deb \
    packages/xaac-thin-client-vpn_1.0.0_all.deb \
    packages/xaac-thinclient_1.0.0_all.deb
do
    if [ ! -f "$artifact" ] || ! dpkg-deb --info "$artifact" >/dev/null 2>&1; then
        printf 'Error: artefacte de producció absent o invàlid: %s\n' "$artifact" >&2
        exit 4
    fi
done

if [ -s assets/release/xaac-archive-keyring.gpg ]; then
    printf '%s\n' '[XAAC] Keyring públic de releases: provisionat.'
else
    printf '%s\n' '[XAAC] AVÍS: keyring públic de releases absent; les actualitzacions externes quedaran bloquejades fail-closed.'
fi

printf '%s\n' 'Bloc 10.7 pre-ISO: gate tècnic superat. Encara cal la validació física documentada al Wyse 3040.'
