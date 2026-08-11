# Minimal exact Zorin icon subset for XAAC Thin Client

This directory contains only the 12 symbolic icons referenced directly by XAAC Thin Client.
Each icon is stored as a real SVG file (no symbolic links) and its content matches the exact
effective icon resolved by GTK4 on the Zorin development workstation. This avoids ZIP symlink
loss and avoids shipping unused Zorin icon assets.

The active theme remains `ZorinBlue-Light`; standard GTK fallback is retained through
Adwaita/gnome/hicolor for icons not owned by XAAC Thin Client.
