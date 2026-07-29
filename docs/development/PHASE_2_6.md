# Fase 2.6 — Sistema base systemd

## Objectiu

Configurar el sistema Debian 13 perquè arranque amb systemd sense serveis crítics fallits, amb una consola administrativa temporal, registre limitat i gestió declarativa dels serveis essencials.

## Configuració

`config/systemd.yaml` defineix:

- target predeterminat;
- disponibilitat de `getty@tty1`;
- límits de `systemd-journald`;
- directoris gestionats per `systemd-tmpfiles`;
- unitats habilitades;
- unitats deshabilitades;
- unitats emmascarades.

La configuració inicial usa `multi-user.target`. La sessió gràfica i el target gràfic es configuraran en el Bloc 4.

## Política inicial

Es mantenen els components imprescindibles de systemd i es redueixen operacions que poden generar escriptures o comportaments no adequats per a un thin client:

- journald persistent limitat a 96 MiB;
- journal temporal limitat a 32 MiB;
- retenció màxima de set dies;
- compressió activada;
- `systemd-tmpfiles-clean.timer` habilitat;
- serveis APT automàtics deshabilitats fins al Bloc 10;
- espera global de xarxa deshabilitada;
- suspensió i hibernació emmascarades.

## Ordres

Planificació segura:

```bash
.venv/bin/xaac-os --root . configure-systemd --dry-run
```

Execució real:

```bash
sudo .venv/bin/xaac-os --root . configure-systemd
```

## Fitxers generats

- `/etc/systemd/journald.conf.d/20-xaac.conf`
- `/etc/tmpfiles.d/20-xaac.conf`
- `/etc/systemd/system/default.target`
- enllaços de serveis dins de `/etc/systemd/system/`

## Seguretat i idempotència

- validació estricta de noms d’unitat;
- rebuig de rutes `tmpfiles` insegures;
- detecció de polítiques contradictòries;
- escriptura atòmica;
- protecció davant enllaços simbòlics inesperats;
- activació mitjançant enllaços, sense arrancar systemd dins del `chroot`;
- mode `--dry-run` executable sense privilegis.

## Proves

La fase incorpora proves positives, negatives, de seguretat, idempotència funcional, absència d’unitats i integració CLI/manifest. Les comprovacions reals d’arrencada i temps inicial s’afegiran a les proves d’imatge i UEFI de la Fase 2.8.

## Limitacions conegudes

Aquesta fase no crea encara la sessió gràfica ni activa `graphical.target`. Tampoc valida un boot real; això requereix la imatge completa de la Fase 2.8.
