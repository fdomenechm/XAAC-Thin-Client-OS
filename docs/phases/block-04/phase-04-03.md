# Fase 4.3 — Gestor de sessió

## Objectiu

Configurar un gestor de sessió gràfica mínim que inicie automàticament una única sessió dedicada per a `xaac-kiosk`, sense exposar un selector de sessions ni un greeter interactiu.

## Decisions

- `greetd` és el gestor de sessió controlat.
- La sessió principal és Wayland i executa `labwc` amb la configuració XAAC.
- L'autologin queda restringit a `xaac-kiosk` en el VT 1.
- GDM, LightDM, SDDM i XDM es declaren incompatibles.
- El llançador exporta les variables XDG i GTK necessàries.
- El llançament de XAAC Thin Client s'incorporarà en la fase 4.5.

## Ordre

```bash
xaac-os configure-session-manager --dry-run
xaac-os configure-session-manager
```

## Fitxers generats

- `/etc/greetd/config.toml`
- `/usr/local/libexec/xaac-session`
- `/usr/share/wayland-sessions/xaac-kiosk.desktop`
- `/etc/xaac/session/session-manager.env`
- `/etc/xaac/session/session-manager-policy.json`

## Seguretat

La configuració es valida abans d'escriure, rebutja rutes insegures i enllaços simbòlics, usa escriptura atòmica i limita el fitxer de `greetd` a mode `0600`.
