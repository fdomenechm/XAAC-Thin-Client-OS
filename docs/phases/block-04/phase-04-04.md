# Fase 4.4 — Usuari de quiosc

Aquesta fase formalitza el compte dedicat `xaac-kiosk` utilitzat per la sessió gràfica.

## Decisions

- compte de sistema bloquejat;
- shell `/usr/sbin/nologin`;
- home persistent i restringit a `/var/lib/xaac-kiosk`;
- grups mínims `audio`, `video`, `input` i `render`;
- variables XDG separades per configuració, estat, memòria cau i runtime;
- memòria cau i runtime fora de l'espai persistent;
- permisos `0750` al home i `0700` als directoris de runtime;
- configuració idempotent i protegida contra enllaços simbòlics.

## Ordre

```bash
xaac-os configure-kiosk-user --dry-run
xaac-os configure-kiosk-user
```
