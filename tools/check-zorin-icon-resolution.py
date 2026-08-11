#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

TARGETS = [
    "auth-sim-symbolic",
    "computer-symbolic",
    "dialog-error-symbolic",
    "dialog-warning-symbolic",
    "help-about-symbolic",
    "network-offline-symbolic",
    "network-server-symbolic",
    "network-transmit-receive-symbolic",
    "network-wired-symbolic",
    "system-search-symbolic",
    "system-shutdown-symbolic",
    "utilities-system-monitor-symbolic",
]

sandbox = Path(os.environ["XAAC_VISUAL_SANDBOX"]).resolve()
sandbox_icons = (sandbox / "data" / "icons").resolve()

display = Gdk.Display.get_default()
if display is None:
    print("ERROR: no hi ha display GTK.", file=sys.stderr)
    sys.exit(2)

settings = Gtk.Settings.get_for_display(display)
settings.set_property("gtk-icon-theme-name", "XAAC-Zorin-Light")

theme = Gtk.IconTheme.get_for_display(display)

print("Tema:", settings.get_property("gtk-icon-theme-name"))
print("Search path GTK:")
for p in theme.get_search_path():
    print("  ", p)

print("\nResolució de les 12 icones objectiu:")
errors = 0

for name in TARGETS:
    icon = theme.lookup_icon(
        name,
        None,
        16,
        1,
        Gtk.TextDirection.NONE,
        Gtk.IconLookupFlags(0),
    )
    f = icon.get_file() if icon is not None else None
    path = Path(f.get_path()).resolve() if f is not None and f.get_path() else None

    if path is None:
        print(f"  ERROR {name}: no resolta")
        errors += 1
        continue

    try:
        path.relative_to(sandbox_icons)
        local = True
    except ValueError:
        local = False

    digest = ""
    if path.is_file():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]

    status = "OK" if local else "EXTERN"
    print(f"  {status:6} {name:38} -> {path}  sha256={digest}")
    if not local:
        errors += 1

if errors:
    print(
        f"\nERROR: {errors} icona(es) objectiu no s'estan obtenint del sandbox.",
        file=sys.stderr,
    )
    sys.exit(1)

print("\nOK: les 12 icones objectiu es resolen exclusivament des dels assets del Thin Client OS.")
