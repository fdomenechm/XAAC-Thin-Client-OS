# Fase 10.6 — Actualització controlada del sistema base

La Fase 10.6 incorpora l'actualització de manteniment i seguretat de la plataforma Debian 13 que sustenta XAAC Thin Client OS. No substitueix l'actualitzador transaccional dels tres components XAAC de la Fase 10.2: són dos canals separats.

## Política

El sistema base només pot actualitzar-se dins de **Debian 13 / trixie**. Les fonts autoritzades són:

- `trixie`;
- `trixie-updates`;
- `trixie-security`.

Totes utilitzen HTTPS i el keyring oficial `/usr/share/keyrings/debian-archive-keyring.gpg`. Les fonts APT alienes a aquesta política fan que l'actualització es bloquege.

No estan permesos:

- `dist-upgrade`;
- `full-upgrade`;
- canvi de release major;
- eliminació de paquets;
- downgrades;
- modificació per APT de `xaac-thinclient`, `xaac-thin-client-vpn` o `xaac-agent`;
- actualitzacions automàtiques o reboot automàtic.

`apt-daily` i `apt-daily-upgrade` continuen emmascarats.

## Ordres administratives

```sh
sudo xaac-update-admin os-status
sudo xaac-update-admin os-check
sudo xaac-update-admin os-update --yes
```

`os-check` executa un preflight i rebutja l'operació si el terminal ha arrancat en mode Recovery. Després actualitza els índexs APT i simula exactament `apt-get upgrade --with-new-pkgs --no-remove`. El pla es rebutja si implica eliminacions, downgrades, paquets XAAC protegits o supera els límits de seguretat.

`os-update` repeteix el check, descarrega primer tots els paquets amb `--download-only`, reverifica que el pla no haja canviat i instal·la després amb `--no-download`. Per tant, la fase de `dpkg` no depèn que la xarxa continue disponible. Els conffiles locals es preserven amb `--force-confdef --force-confold`.

Abans de la instal·lació es desa un checkpoint root-only amb l'estat de `dpkg`, les versions instal·lades, hashes de les fonts APT i el pla aprovat. Aquest checkpoint és evidència de recuperació; **no es promet un downgrade automàtic de tot Debian**, perquè els scripts de manteniment dels paquets no garanteixen que un downgrade massiu siga segur.

Si l'actualització falla i `dpkg --configure -a` no pot recuperar una situació coherent, l'estat passa a `failed_requires_recovery`. En aquest cas s'ha d'arrancar **XAAC Thin Client OS — Recovery** i executar:

```sh
sudo xaac-recovery status
sudo xaac-recovery repair --yes
```

## Reinici

`os-update` no reinicia automàticament. Marca `reboot_required` quan Debian crea `/var/run/reboot-required` o quan el pla inclou kernel, initramfs, GRUB, shim, systemd o libc. L'administrador decideix quan reiniciar el terminal.

## Validació

Gate focalitzat:

```sh
./scripts/validate-block10-phase6.sh
```

El gate final del Bloc 10 incorpora també aquesta fase abans de construir la ISO.
