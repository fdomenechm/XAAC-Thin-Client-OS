# Fase 5.5 — Sistema de fitxers del quiosc

## Objectiu

Fer que l'estat escrit per `xaac-kiosk` siga efímer, mínim i eliminat de manera determinista en començar i acabar cada sessió.

## Implementació

- Política declarativa `config/kiosk-filesystem.yaml`, estricta i amb denegació per defecte.
- `/home/xaac-kiosk` muntat sobre `tmpfs` de 192 MiB amb `nosuid,nodev,noexec`.
- Directoris permesos limitats a configuració XAAC, memòria cau XAAC i descàrregues.
- Descàrregues limitades, no executables i eliminades al final de la sessió.
- `umask 0077`, propietat exclusiva de `xaac-kiosk` i prohibició d'enllaços seguits per la política.
- Servei de neteja fail-closed i script restringit al mateix sistema de fitxers.
- Configuració `tmpfiles.d`, variables d'entorn i política JSON auditable.

## Ordre

```bash
xaac-os configure-kiosk-filesystem --dry-run
xaac-os configure-kiosk-filesystem
```

## Fitxers efectius

- `/etc/systemd/system/home-xaac\x2dkiosk.mount`
- `/usr/lib/tmpfiles.d/xaac-kiosk-filesystem.conf`
- `/usr/local/libexec/xaac/kiosk-cleanup`
- `/etc/systemd/system/xaac-kiosk-cleanup.service`
- `/etc/xaac/kiosk/environment.d/30-filesystem.conf`
- `/etc/xaac/kiosk/filesystem-policy.json`

## Límits

Aquesta fase no defineix encara polítiques específiques per a dispositius USB o automuntatge; corresponen a la Fase 5.6.
