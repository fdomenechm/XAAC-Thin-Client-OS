# Fase 5.4 — Control dels TTY

## Objectiu

Impedir que l'usuari de quiosc abandone la sessió gràfica mitjançant terminals virtuals i conservar un únic canal local d'administració autenticada.

## Política aplicada

`config/tty-control.yaml` estableix una política de denegació per defecte:

- els TTY 1–11 no disposen de `getty` ni `autovt`;
- `tty12` queda reservat per a administració local;
- l'únic usuari admés és `xaac-admin`;
- l'accés exigeix autenticació mitjançant `/bin/login`;
- `systemd-logind` no crea terminals virtuals automàtics;
- `Ctrl+Alt+F12` és l'única drecera reservada i apunta al TTY administratiu;
- la sessió `xaac-kiosk` no rep `CAP_SYS_TTY_CONFIG` ni autorització per canviar de TTY.

## Fitxers generats

- `/etc/systemd/logind.conf.d/30-xaac-tty-control.conf`
- `/etc/systemd/system/getty@tty12.service.d/30-xaac-admin.conf`
- `/usr/local/libexec/xaac/tty-admin-login`
- `/etc/securetty.d/xaac-admin.conf`
- `/etc/xaac/kiosk/tty-control.json`
- màscares systemd per a `getty@tty1..11.service` i `autovt@tty1..11.service`
- enllaç d'activació de `getty@tty12.service`

## Execució

```bash
xaac-os configure-tty-control --dry-run
xaac-os configure-tty-control
```

## Seguretat

La configuració és estricta, idempotent i atòmica. Rebutja rootfs insegurs, rutes amb escapament, fitxers de destinació que siguen enllaços simbòlics i conflictes amb directoris existents.

El compte `xaac-admin` continua inicialment bloquejat segons `config/users.yaml`; l'activació i canvi obligatori de contrasenya es desenvoluparan en la Fase 7.6. Per tant, el TTY queda preparat però no permet accés fins que el perfil administrador siga habilitat explícitament.

## Proves

Les proves cobreixen:

- validació positiva i negativa de l'esquema;
- reserva coherent de `tty12`;
- deshabilitació completa dels TTY 1–11;
- autenticació exclusiva de `xaac-admin`;
- generació dels fitxers i unitats systemd;
- modes de permisos;
- idempotència;
- protecció contra enllaços simbòlics;
- exposició de l'ordre CLI.
