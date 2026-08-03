# XAAC Thin Client OS

**XAAC Thin Client OS 1.0.0** és una distribució especialitzada basada en Debian 13,
optimitzada per al Dell Wyse 3040 amb 2 GB de RAM i 8 GB d'eMMC. Proporciona una
sessió gràfica segura en mode quiosc per executar XAAC Thin Client, XAAC Thin Client
Agent i el client personalitzat XAAC Remote Support basat en RustDesk.

## Estat del projecte

- Versió estable: **1.0.0**
- Plataforma base: **Debian 13**
- Arquitectura objectiu: **amd64**
- Maquinari principal: **Dell Wyse 3040**
- Entorn de desenvolupament: **Python 3.13**
- Llicència: **EUPL v1.2 o posterior**

El calendari inicial de desenvolupament està complet. L'històric de les fases es
conserva a [`docs/phases/`](docs/phases/README.md).

## Característiques principals

- Sessió dedicada `xaac-kiosk` amb inici automàtic i restriccions de quiosc.
- Administració local separada mitjançant `xaac-admin`.
- Accés OpenSSH restringit per usuari, clau i xarxes autoritzades.
- Integració amb XAAC Thin Client, XAAC Agent i XAAC Remote Support.
- Configuració declarativa YAML i aplicació transaccional amb rollback.
- Hardening amb systemd, AppArmor, nftables, sysctl i control de dispositius.
- Actualitzacions signades, desplegament per anells i recuperació en diversos nivells.
- Constructors per a ISO, IMG, PXE, instal·lador, clonació i release final.
- Proves automatitzades de codi, imatge, maquinari, rendiment i estabilitat.

## Inici ràpid de desenvolupament

```bash
./scripts/create-venv.sh
./scripts/run-tests.sh
.venv/bin/xaac-os version
.venv/bin/xaac-os --root . validate
```

Python ha de ser 3.13. El projecte declara la restricció `>=3.13,<3.14`.

## Construcció

La configuració es troba principalment a `config/*.yaml` i als perfils de
`profiles/`. Les operacions destructives exigeixen privilegis, confirmació explícita
i un entorn preparat. Exemples:

```bash
.venv/bin/xaac-os --root . prepare
.venv/bin/xaac-os --root . bootstrap --dry-run
.venv/bin/xaac-os --root . build-iso
.venv/bin/xaac-os --root . build-img
.venv/bin/xaac-os --root . build-final-release
```

Consulteu la [guia de construcció](docs/getting-started/build.md) abans d'executar
constructors reals.

## Documentació

El punt d'entrada oficial és [`docs/README.md`](docs/README.md).

- [Instal·lació i primers passos](docs/getting-started/README.md)
- [Administració i operació](docs/administration/README.md)
- [Arquitectura](docs/architecture/README.md)
- [Desenvolupament](docs/development/README.md)
- [Referència tècnica](docs/reference/README.md)
- [Release 1.0.0](docs/release/README.md)
- [Històric de fases](docs/phases/README.md)

## Estructura del repositori

```text
src/          codi Python del constructor i de la CLI
tests/        proves automatitzades
config/       configuració declarativa del sistema
profiles/     perfils comuns i del Dell Wyse 3040
builder/      recursos del constructor d'imatges
templates/    plantilles del sistema
hooks/        hooks controlats de construcció
packaging/    definicions dels paquets Debian
recovery/     recursos de recuperació
docs/         documentació oficial i històrica
scripts/      scripts de desenvolupament i construcció
```

## Seguretat i secrets

No s'han d'incloure claus privades, tokens, credencials, certificats particulars ni
identitats de dispositiu en el repositori, en la imatge mestra o en els ZIP
consolidats. Les signatures oficials es generen únicament amb una clau autoritzada
fora del codi font.

## Llicència

European Union Public Licence (EUPL) v1.2 o posterior.

## Generació de la ISO des de PyCharm

Des del terminal integrat de PyCharm, situat a l'arrel del projecte:

```bash
sudo ./scripts/install-build-dependencies.sh
./scripts/build-production-iso.sh
```

El segon script eleva privilegis amb `sudo` i usa una cadena separada per responsabilitats:

1. `build-rootfs` construeix el sistema Debian reutilitzable sense instal·lar GRUB sobre cap disc.
2. `mksquashfs` genera el sistema de fitxers comprimit de la ISO.
3. `build-iso` prepara l'arbre ISO i `grub-mkrescue` genera l'arrencada híbrida BIOS/UEFI.

Aquesta separació evita executar `grub-install` dins del `chroot`, operació reservada
a les imatges de disc instal·lables. L'artefacte final queda en:

```text
.build/artifacts/xaac-thin-client-os-amd64.iso
```

La ISO de desenvolupament es pot generar sense clau GPG. Per exigir signatura:

```bash
XAAC_ISO_SIGNING_KEY=<ID_CLAU> XAAC_REQUIRE_ISO_SIGNATURE=1 \
  ./scripts/build-production-iso.sh
```

## Construcció de la ISO de producció

El constructor de producció és independent del constructor d'imatges de disc antic i està dividit en sis fases:

```text
rootfs → configure → boot → squashfs → iso → verify
```

Instal·la primer les dependències:

```bash
sudo ./scripts/install-build-dependencies.sh
```

Construcció completa i neta:

```bash
./scripts/build-production-iso.sh --clean
```

L'artefacte queda en:

```text
.build/artifacts/xaac-thin-client-os-amd64.iso
.build/artifacts/xaac-thin-client-os-amd64.iso.sha256
```

Per reprendre o diagnosticar una fase concreta:

```bash
./scripts/build-production-iso.sh --phase configure
./scripts/build-production-iso.sh --phase boot
./scripts/build-production-iso.sh --phase squashfs
./scripts/build-production-iso.sh --phase iso
./scripts/build-production-iso.sh --phase verify
```

Els logs es guarden en `.build/production/logs/`. El constructor ISO no executa `grub-install`: la compatibilitat BIOS/UEFI es genera directament amb `grub-mkrescue`.

### Seguretat dels muntatges del chroot

El constructor munta temporalment `/dev`, `/proc`, `/sys` i `/run` dins del rootfs.
Els muntatges recursius es converteixen immediatament en `rslave`, de manera que
les operacions de desmuntatge del chroot no es propaguen mai cap al sistema host.
La neteja comprova cada punt amb `mountpoint`, desmunta primer `/dev/pts` i només
accepta rutes confinades sota `.build/production/rootfs`. El llançador incorpora
un `trap` per executar aquesta neteja també davant d'interrupcions.

Això permet repetir: 

```bash
./scripts/build-production-iso.sh --clean
```

sense deixar `/dev/pts` de l'amfitrió inutilitzable ni obligar a reiniciar la
màquina constructora.

### Consoles virtuals i recuperació de l'instal·lador

L'autologin del compte `xaac-kiosk` només s'aplica a `tty1`. Les consoles
`tty2` a `tty6` reinicien explícitament les credencials importades d’`agetty` i
executen un `agetty` autenticat normal. Això evita que una credencial global
`agetty.autologin` creada en temps d’arrencada propague l’autologin a totes les TTY. Quan
l'entrada d'instal·lació pren `tty1`, el servei entra en conflicte únicament amb
`getty@tty1.service`. Si l'instal·lador falla, `OnFailure` activa un servei de
recuperació que torna a iniciar el `getty` de `tty1`.

El bootstrap es fa en dues etapes: `debootstrap --variant=minbase` crea únicament Debian base i, després, la fase `configure` executa `apt-get update` i instal·la kernel, firmware i resta de paquets des dels components definits en `config/build.yaml`. Això evita intentar resoldre `firmware-linux` o `firmware-misc-nonfree` durant el bootstrap inicial.

### Política de configuració Live i usuari de sessió

XAAC Thin Client OS configura durant la construcció el compte `xaac-kiosk`, la
llengua, el teclat, la zona horària i la política de consoles. Per evitar que
Debian `live-config` torne a modificar aquests valors durant cada arrencada, les
entrades GRUB incorporen explícitament:

```text
live-config.nocomponents
```

A més, el rootfs inclou `/etc/live/config.conf.d/xaac.conf` amb la mateixa
política. D'aquesta manera `live-config` no crea l'usuari genèric `user`, no
reescriu `getty@.service` i no aplica autologin a consoles secundàries.

### Llengua i teclat de la ISO

La configuració predeterminada de XAAC Thin Client OS és:

```text
Llengua:             català (`ca_ES.UTF-8`)
Teclat:              espanyol (`es`)
Model de teclat:     `pc105`
Variant:             cap
Zona horària:        `Europe/Madrid`
```

La configuració declarativa es troba en `config/localization.yaml`. El constructor
instal·la `keyboard-configuration`, `console-setup` i `console-setup-linux`, escriu
`/etc/default/keyboard` i `/etc/default/locale`, i executa
`dpkg-reconfigure keyboard-configuration` de manera no interactiva. Aquests
valors queden integrats directament al rootfs; no depenen de `live-config` ni de
paràmetres variables de l'arrencada.

Després de construir la ISO es pot verificar amb:

```bash
grep -n 'linux /live/vmlinuz' .build/production/iso-staging/boot/grub/grub.cfg
cat .build/production/rootfs/etc/default/keyboard
cat .build/production/rootfs/etc/default/locale
```

### Instal·lador incremental — pas 1

La primera iteració de l’instal·lador és deliberadament no destructiva. L’entrada
`Install XAAC Thin Client OS` arranca amb `xaac.mode=installer` i
`live-config.nocomponents`. La política de consoles queda controlada només per
XAAC: `tty1` és reservada per al quiosc o l'instal·lador, mentre que `tty2` a
`tty6` conserven el `getty` estàndard de Debian i requereixen autenticació.

`systemd.unit=multi-user.target`, inicia `xaac-installer-welcome.service` sobre
`tty1` i mostra una pantalla de benvinguda. En aquest pas no es detecten,
particionen, formaten ni modifiquen discs. En prémer Retorn, el sistema es
reinicia. L’opció `XAAC diagnostics (read-only)` manté el comportament Live.

Aquesta fita només valida el menú de GRUB, el paràmetre d’arrencada i el servei
de consola abans d’afegir cap operació destructiva.


### Instal·lador incremental — pas 2

L’opció d’instal·lació detecta els discs escrivibles, mostra dispositiu, mida i model i permet seleccionar-ne un. Aquest pas és estrictament no destructiu: no particiona, no formata ni escriu cap dada.
