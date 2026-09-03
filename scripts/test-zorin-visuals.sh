#!/usr/bin/env bash
set -euo pipefail

OS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XAAC_ROOT="${XAAC_ROOT:-$HOME/ws/xaactc}"
SANDBOX="${XAAC_VISUAL_SANDBOX:-/tmp/xaac-os-visual-test}"

usage() {
  cat <<EOF
Ús:
  XAAC_ROOT=/ruta/al/xaactc $0 [--keep]

Prova visual ràpida de XAAC amb els assets del Thin Client OS, sense ISO.

La prova és estricta per a les 12 icones que XAAC Thin Client demana:
abans d'obrir l'aplicació verifica que totes es resolen des del sandbox
i no des del tema Zorin instal·lat a la màquina host.
EOF
}

KEEP=0
case "${1:-}" in
  --keep) KEEP=1 ;;
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) usage >&2; exit 2 ;;
esac

PYTHON="$XAAC_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || { echo "ERROR: no existeix $PYTHON" >&2; exit 1; }

ICON_SOURCE="$OS_ROOT/assets/zorin-icons/XAAC-Zorin-Light"
THEME_SOURCE="$OS_ROOT/assets/zorin-theme/ZorinBlue-Light"

[[ -d "$ICON_SOURCE" ]] || { echo "ERROR: falta $ICON_SOURCE" >&2; exit 1; }
[[ -d "$THEME_SOURCE" ]] || { echo "ERROR: falta $THEME_SOURCE" >&2; exit 1; }

rm -rf "$SANDBOX"
mkdir -p \
  "$SANDBOX/config/gtk-3.0" \
  "$SANDBOX/config/gtk-4.0" \
  "$SANDBOX/data/icons" \
  "$SANDBOX/data/themes"

cp -a "$ICON_SOURCE" "$SANDBOX/data/icons/"
cp -a "$THEME_SOURCE" "$SANDBOX/data/themes/"

cat >"$SANDBOX/config/gtk-3.0/settings.ini" <<'EOF'
[Settings]
gtk-theme-name=ZorinBlue-Light
gtk-icon-theme-name=XAAC-Zorin-Light
EOF

cat >"$SANDBOX/config/gtk-4.0/settings.ini" <<'EOF'
[Settings]
gtk-theme-name=ZorinBlue-Light
gtk-icon-theme-name=XAAC-Zorin-Light
EOF

if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
  gtk4-update-icon-cache -f "$SANDBOX/data/icons/XAAC-Zorin-Light" >/dev/null || true
elif command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "$SANDBOX/data/icons/XAAC-Zorin-Light" >/dev/null || true
fi

export XAAC_VISUAL_SANDBOX="$SANDBOX"
export XDG_CONFIG_HOME="$SANDBOX/config"
export XDG_DATA_HOME="$SANDBOX/data"
# Sandbox first; system data remains only as fallback for GTK's own internal icons.
export XDG_DATA_DIRS="$SANDBOX/data:/usr/local/share:/usr/share"
export GTK_THEME="ZorinBlue-Light"
export PYTHONPATH="$XAAC_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "============================================================"
echo " XAAC visual test — STRICT TARGET ICON CHECK"
echo " XAAC:    $XAAC_ROOT"
echo " Sandbox: $SANDBOX"
echo "============================================================"
echo

# Mandatory preflight: every XAAC-owned icon must come from the sandbox.
"$PYTHON" "$OS_ROOT/tools/check-zorin-icon-resolution.py"

echo
echo "Preflight correcte. Llançant XAAC..."
echo "Tanca la finestra per acabar la prova."
echo

cd "$XAAC_ROOT"

if [[ -x "$XAAC_ROOT/.venv/bin/xaac-thinclient" ]]; then
  "$XAAC_ROOT/.venv/bin/xaac-thinclient"
elif "$PYTHON" -c 'import importlib.util,sys; sys.exit(0 if importlib.util.find_spec("xaac_thinclient.__main__") else 1)' 2>/dev/null; then
  "$PYTHON" -m xaac_thinclient
else
  MAIN="$("$PYTHON" - <<'PY'
from pathlib import Path
for p in Path("src").rglob("*.py"):
    s=p.read_text(errors="ignore")
    if "XaacThinClientApplication" in s and "run(" in s:
        print(p)
        break
PY
)"
  [[ -n "$MAIN" ]] || {
    echo "ERROR: no he pogut detectar l'entry point de XAAC Thin Client." >&2
    exit 1
  }
  "$PYTHON" "$MAIN"
fi

if [[ "$KEEP" -eq 0 ]]; then
  rm -rf "$SANDBOX"
else
  echo "Sandbox conservat en $SANDBOX"
fi
