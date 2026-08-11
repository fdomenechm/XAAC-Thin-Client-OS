#!/usr/bin/env bash
set -euo pipefail

OS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XAAC_ROOT="${XAAC_ROOT:-$HOME/ws/xaactc}"
SANDBOX="${XAAC_VISUAL_SANDBOX:-/tmp/xaac-os-visual-test}"

usage() {
  cat <<EOF
Ús:
  XAAC_ROOT=/ruta/al/xaactc $0 [--keep]

Prova XAAC Thin Client amb els assets GTK/icones del codi actual de
XAAC Thin Client OS, sense construir cap ISO.

Per defecte XAAC_ROOT=$HOME/ws/xaactc
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
[[ -d "$OS_ROOT/assets/zorin-icons/ZorinBlue-Light" ]] || {
  echo "ERROR: falten assets/zorin-icons/ZorinBlue-Light" >&2; exit 1;
}
[[ -d "$OS_ROOT/assets/zorin-theme/ZorinBlue-Light" ]] || {
  echo "ERROR: falten assets/zorin-theme/ZorinBlue-Light" >&2; exit 1;
}

rm -rf "$SANDBOX"
mkdir -p \
  "$SANDBOX/config/gtk-3.0" \
  "$SANDBOX/config/gtk-4.0" \
  "$SANDBOX/data/icons" \
  "$SANDBOX/data/themes"

# Use exactly the icon/theme payload currently shipped by XAAC Thin Client OS.
cp -a "$OS_ROOT/assets/zorin-icons/ZorinBlue-Light" "$SANDBOX/data/icons/"
cp -a "$OS_ROOT/assets/zorin-theme/ZorinBlue-Light" "$SANDBOX/data/themes/"

cat >"$SANDBOX/config/gtk-3.0/settings.ini" <<'EOF'
[Settings]
gtk-theme-name=ZorinBlue-Light
gtk-icon-theme-name=ZorinBlue-Light
EOF

cat >"$SANDBOX/config/gtk-4.0/settings.ini" <<'EOF'
[Settings]
gtk-theme-name=ZorinBlue-Light
gtk-icon-theme-name=ZorinBlue-Light
EOF

if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
  gtk4-update-icon-cache -f "$SANDBOX/data/icons/ZorinBlue-Light" >/dev/null || true
elif command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "$SANDBOX/data/icons/ZorinBlue-Light" >/dev/null || true
fi

echo "============================================================"
echo " XAAC visual test — NO ISO"
echo " XAAC:    $XAAC_ROOT"
echo " Sandbox: $SANDBOX"
echo " Icons:   $SANDBOX/data/icons/ZorinBlue-Light"
echo " Theme:   $SANDBOX/data/themes/ZorinBlue-Light"
echo "============================================================"
echo
echo "La finestra següent usa el payload visual del Thin Client OS."
echo "Tanca XAAC per acabar la prova."
echo

cd "$XAAC_ROOT"

# Keep system XDG dirs as fallbacks for GTK's own internal icons, while putting
# the test payload first.  This mirrors the intended OS behavior but guarantees
# our ZorinBlue-Light subset wins when it contains a requested icon.
export XDG_CONFIG_HOME="$SANDBOX/config"
export XDG_DATA_HOME="$SANDBOX/data"
export XDG_DATA_DIRS="$SANDBOX/data:/usr/local/share:/usr/share"
export GTK_THEME="ZorinBlue-Light"
export PYTHONPATH="$XAAC_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# Determine the development entry point without installing/changing anything.
if [[ -x "$XAAC_ROOT/.venv/bin/xaac-thinclient" ]]; then
  "$XAAC_ROOT/.venv/bin/xaac-thinclient"
elif "$PYTHON" -c 'import importlib.util,sys; sys.exit(0 if importlib.util.find_spec("xaac_thinclient.__main__") else 1)' 2>/dev/null; then
  "$PYTHON" -m xaac_thinclient
else
  MAIN="$("$PYTHON" - <<'PY'
from pathlib import Path
import re
for p in Path("src").rglob("*.py"):
    s=p.read_text(errors="ignore")
    if "XaacThinClientApplication" in s and ("app.run(" in s or ".run(" in s):
        print(p)
        break
PY
)"
  if [[ -z "$MAIN" ]]; then
    echo "ERROR: no he pogut detectar l'entry point de XAAC Thin Client." >&2
    echo "Executa'l des de PyCharm afegint aquestes variables d'entorn:" >&2
    echo "XDG_CONFIG_HOME=$SANDBOX/config" >&2
    echo "XDG_DATA_HOME=$SANDBOX/data" >&2
    echo "XDG_DATA_DIRS=$SANDBOX/data:/usr/local/share:/usr/share" >&2
    echo "GTK_THEME=ZorinBlue-Light" >&2
    exit 1
  fi
  "$PYTHON" "$MAIN"
fi

if [[ "$KEEP" -eq 0 ]]; then
  rm -rf "$SANDBOX"
else
  echo "Sandbox conservat en $SANDBOX"
fi
