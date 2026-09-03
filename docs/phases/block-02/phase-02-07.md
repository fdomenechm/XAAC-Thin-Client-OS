# Fase 2.7 — Localització i consola

Aquesta fase configura de manera declarativa i reproduïble la localització del sistema base Debian 13.

## Abast

- locale principal `ca_ES.UTF-8`;
- fallbacks `es_ES.UTF-8` i `en_US.UTF-8`;
- zona horària `Europe/Madrid`;
- teclat espanyol amb variant catalana (`es(cat)`);
- consola UTF-8 amb font Terminus;
- generació de locales i actualització de l'entorn global;
- mode `--dry-run`, log i manifest de construcció.

## Configuració

El fitxer `config/localization.yaml` conté tots els paràmetres. L'esquema rebutja claus desconegudes, locales malformades, rutes insegures i opcions de teclat no vàlides.

## Execució

```bash
.venv/bin/xaac-os --root . configure-localization --dry-run
sudo .venv/bin/xaac-os --root . configure-localization
```

## Fitxers generats

- `/etc/locale.gen`
- `/etc/default/locale`
- `/etc/default/keyboard`
- `/etc/default/console-setup`
- `/etc/timezone`
- `/etc/localtime`

L'execució real requereix `locale-gen`, `update-locale` i la zona horària corresponent dins del rootfs.
