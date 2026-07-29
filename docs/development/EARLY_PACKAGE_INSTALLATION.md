# Fase 2.3 — Instal·lació del sistema base

Aquesta fase instal·la dins del `rootfs` Debian 13 els paquets resolts de manera
determinista per `config/packages.yaml` i pel perfil de maquinari actiu.

## Objectius

- executar `apt-get update` dins del `rootfs` mitjançant `chroot`;
- instal·lar només els paquets efectius, sense recomanats ni suggerits;
- evitar qualsevol diàleg interactiu de `debconf`;
- validar que el bootstrap i la configuració APT s'han completat;
- registrar totes les ordres i la seua eixida;
- incorporar el pla i el resultat al manifest de construcció.

## Mode de planificació

```bash
.venv/bin/xaac-os --root . install-packages --dry-run
```

El mode `--dry-run` no requereix privilegis ni executa APT. Escriu les ordres
previstes en `logs/package-installation.log`.

## Execució real

Després de `bootstrap` i `configure-apt`:

```bash
sudo .venv/bin/xaac-os --root . install-packages
```

L'execució real exigeix privilegis de `root` i comprova l'existència de:

- `/etc/debian_version`;
- `/usr/bin/apt-get`;
- `/etc/apt/sources.list.d/xaac.sources`;
- `/etc/apt/apt.conf.d/99xaac-minimal`.

## Reproduïbilitat i seguretat

Els paquets s'ordenen i es dedupliquen. Els noms invàlids i qualsevol solapament
entre inclusions i exclusions són rebutjats abans de l'execució. APT s'executa
amb `DEBIAN_FRONTEND=noninteractive`, locale estable i sense paquets recomanats
o suggerits.
