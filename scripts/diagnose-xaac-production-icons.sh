#!/usr/bin/env bash
set -euo pipefail

TARGET_USER="${TARGET_USER:-xaac-kiosk}"

EXPECTED_auth_sim_symbolic="01e42890afdc3082b248295d8a4ba61d91af8b836ee808f7fbfbd0002de4d9ae"
EXPECTED_computer_symbolic="cad86a1164bf8a8f2c7d568f0125d9899be9b9c02e0ef65420999a22124effa7"
EXPECTED_dialog_error_symbolic="05a85ec0f73e64b10fc062e4bb0f20bcafbad028c85c18164b1bf045cbe4b4a2"
EXPECTED_dialog_warning_symbolic="76e734f1e6492dc1c5ac46228a2320e5338bf7ad1c7c41118d7280ec79d0bc55"
EXPECTED_help_about_symbolic="b09b47be074be06f0bf4cde242233970cb99e30b8ac62e3d312b61389e8c8432"
EXPECTED_network_offline_symbolic="d024ef36a3c14303a2001aa587f80197d0ec2138fe84ad5e2a91b9d3a3e3bfdc"
EXPECTED_network_server_symbolic="f24cfc83fc059906e44bcd91f199f825a94685f059abd8e315a98c58389b1e22"
EXPECTED_network_transmit_receive_symbolic="8ce73843ad3eed9b4792949bf7016526e2a2be20b30fea38c7fbe90d8a36c4a3"
EXPECTED_network_wired_symbolic="274e8ae73d4e2da875f5963eae376ab56c0723df117614dce0701da88ef44270"
EXPECTED_system_search_symbolic="4fca45d086d58b6f39a477706668487a7a86740ec9859018b0ccd3608a54065e"
EXPECTED_system_shutdown_symbolic="99f7a262eba6ca9dd4336f748f2d5eb31c357a8f97b60076736d27639fe408c7"
EXPECTED_utilities_system_monitor_symbolic="0b6ae88a036b0978c3263bad85d4589b3f944ed240771dd46b46a2a274ecca0e"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: executa aquest script amb sudo." >&2
  exit 1
fi

PID="$(pgrep -u "$TARGET_USER" -f '(^|/)(xaac-thinclient|python.*xaac_thinclient)' | head -n1 || true)"
if [[ -z "$PID" ]]; then
  echo "ERROR: no he trobat cap procés XAAC Thin Client de l'usuari $TARGET_USER." >&2
  echo "Comprova: ps -ef | grep -i xaac" >&2
  exit 2
fi

echo "============================================================"
echo " XAAC Thin Client OS — diagnòstic GTK de producció"
echo "============================================================"
echo "Usuari : $TARGET_USER"
echo "PID    : $PID"
echo "CMD    : $(tr '\0' ' ' < /proc/$PID/cmdline)"
echo

echo "--- Entorn REAL del procés XAAC ---"
for key in \
  DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR XDG_CONFIG_HOME XDG_DATA_HOME \
  XDG_DATA_DIRS XDG_CURRENT_DESKTOP GTK_THEME GDK_BACKEND GDK_SCALE \
  GDK_DPI_SCALE DBUS_SESSION_BUS_ADDRESS
do
  value="$(tr '\0' '\n' < /proc/$PID/environ | sed -n "s/^${key}=//p" | head -n1)"
  printf '%-26s = %s\n' "$key" "${value:-<unset>}"
done
echo

echo "--- Configuració GTK instal·lada ---"
for f in \
  /etc/xaac/gtk-4.0/settings.ini \
  /etc/xaac/gtk-3.0/settings.ini \
  /etc/gtk-4.0/settings.ini \
  /etc/gtk-3.0/settings.ini
do
  if [[ -f "$f" ]]; then
    echo "### $f"
    cat "$f"
    echo
  fi
done

echo "--- Tema XAAC-Zorin-Light instal·lat ---"
if [[ ! -f /usr/share/icons/XAAC-Zorin-Light/index.theme ]]; then
  echo "ERROR: falta /usr/share/icons/XAAC-Zorin-Light/index.theme"
else
  sed -n '1,80p' /usr/share/icons/XAAC-Zorin-Light/index.theme
fi
echo

echo "--- Fitxers del tema ---"
find /usr/share/icons/XAAC-Zorin-Light -maxdepth 4 -type f -o -type l 2>/dev/null | sort
echo

# Capture the exact session environment needed to connect to the running display.
ENV_ARGS=()
while IFS= read -r -d '' entry; do
  case "$entry" in
    DISPLAY=*|WAYLAND_DISPLAY=*|XDG_RUNTIME_DIR=*|XDG_CONFIG_HOME=*|XDG_DATA_HOME=*|XDG_DATA_DIRS=*|XDG_CURRENT_DESKTOP=*|GTK_THEME=*|GDK_BACKEND=*|GDK_SCALE=*|GDK_DPI_SCALE=*|DBUS_SESSION_BUS_ADDRESS=*)
      ENV_ARGS+=("$entry")
      ;;
  esac
done < /proc/"$PID"/environ

TMPPY="$(mktemp /tmp/xaac-prod-icon-probe.XXXXXX.py)"
trap 'rm -f "$TMPPY"' EXIT

cat >"$TMPPY" <<'PY'
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

EXPECTED = {
    "auth-sim-symbolic": "01e42890afdc3082b248295d8a4ba61d91af8b836ee808f7fbfbd0002de4d9ae",
    "computer-symbolic": "cad86a1164bf8a8f2c7d568f0125d9899be9b9c02e0ef65420999a22124effa7",
    "dialog-error-symbolic": "05a85ec0f73e64b10fc062e4bb0f20bcafbad028c85c18164b1bf045cbe4b4a2",
    "dialog-warning-symbolic": "76e734f1e6492dc1c5ac46228a2320e5338bf7ad1c7c41118d7280ec79d0bc55",
    "help-about-symbolic": "b09b47be074be06f0bf4cde242233970cb99e30b8ac62e3d312b61389e8c8432",
    "network-offline-symbolic": "d024ef36a3c14303a2001aa587f80197d0ec2138fe84ad5e2a91b9d3a3e3bfdc",
    "network-server-symbolic": "f24cfc83fc059906e44bcd91f199f825a94685f059abd8e315a98c58389b1e22",
    "network-transmit-receive-symbolic": "8ce73843ad3eed9b4792949bf7016526e2a2be20b30fea38c7fbe90d8a36c4a3",
    "network-wired-symbolic": "274e8ae73d4e2da875f5963eae376ab56c0723df117614dce0701da88ef44270",
    "system-search-symbolic": "4fca45d086d58b6f39a477706668487a7a86740ec9859018b0ccd3608a54065e",
    "system-shutdown-symbolic": "99f7a262eba6ca9dd4336f748f2d5eb31c357a8f97b60076736d27639fe408c7",
    "utilities-system-monitor-symbolic": "0b6ae88a036b0978c3263bad85d4589b3f944ed240771dd46b46a2a274ecca0e",
}

display = Gdk.Display.get_default()
if display is None:
    print("ERROR: Gdk.Display.get_default() és None.")
    print("No s'ha pogut connectar a la mateixa sessió gràfica.")
    sys.exit(3)

settings = Gtk.Settings.get_for_display(display)
theme = Gtk.IconTheme.get_for_display(display)

print("--- GTK4 efectiu en PRODUCCIÓ ---")
print("GTK version        =", Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version())
print("gtk-theme-name     =", settings.get_property("gtk-theme-name"))
print("gtk-icon-theme-name=", settings.get_property("gtk-icon-theme-name"))
print("gtk-font-name      =", settings.get_property("gtk-font-name"))
print()

print("--- Search path GTK4 ---")
for path in theme.get_search_path():
    print(path)
print()

print("--- Resolució efectiva de les 12 icones ---")
errors = 0
for name, expected in EXPECTED.items():
    icon = theme.lookup_icon(
        name,
        None,
        16,
        1,
        Gtk.TextDirection.NONE,
        Gtk.IconLookupFlags(0),
    )
    f = icon.get_file() if icon is not None else None
    path_s = f.get_path() if f is not None else None
    if not path_s:
        print(f"ERROR {name:38} -> <no file>")
        errors += 1
        continue

    path = Path(path_s)
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    hash_ok = digest == expected
    theme_ok = "/XAAC-Zorin-Light/" in str(path)
    status = "OK" if hash_ok and theme_ok else "MISMATCH"
    print(
        f"{status:8} {name:38} -> {path} "
        f"sha256={digest[:16]} expected={expected[:16]}"
    )
    if status != "OK":
        errors += 1

print()
if errors:
    print(f"RESULTAT: {errors} icona(es) no coincideixen amb desenvolupament.")
    sys.exit(1)

print("RESULTAT: 12/12 icones coincideixen exactament amb desenvolupament.")
PY

echo "--- Executant probe GTK4 amb l'entorn del procés real ---"
set +e
sudo -u "$TARGET_USER" env -i \
  HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)" \
  USER="$TARGET_USER" LOGNAME="$TARGET_USER" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  "${ENV_ARGS[@]}" \
  /usr/bin/python3 "$TMPPY"
RC=$?
set -e

echo
echo "============================================================"
if [[ $RC -eq 0 ]]; then
  echo "DIAGNÒSTIC OK"
else
  echo "DIAGNÒSTIC AMB DIFERÈNCIES (codi $RC)"
fi
echo "============================================================"
exit "$RC"
