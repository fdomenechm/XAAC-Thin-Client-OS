# Fase 5.6 — Control de dispositius locals

Aquesta fase aplica una política de denegació per defecte als dispositius locals de la sessió `xaac-kiosk`.

## Abast

- USB governat per política i llistes VID/PID.
- HID, smartcards i impressores autoritzables.
- Càmeres deshabilitades per defecte.
- Emmagatzematge massiu i automuntatge bloquejats.
- Denegació de totes les accions UDisks2 per a `xaac-kiosk`.
- Política JSON auditable.

## Execució

```bash
xaac-os configure-local-device-control --dry-run
xaac-os configure-local-device-control
```

## Fitxers generats

- `/etc/udev/rules.d/80-xaac-kiosk-local-devices.rules`
- `/etc/polkit-1/rules.d/80-xaac-kiosk-udisks.rules`
- `/etc/xaac/kiosk/local-device-control.json`
