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
- XAAC Agent 1.0.0 integrat com a paquet Debian `1.0.0-1`, amb runtime Python 3.13 privat i validació SHA-256 abans de construir la ISO.
- XAAC Thin Client VPN amb provisionament administratiu simplificat mitjançant `xaac-vpn-admin`.
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

El constructor espera i reintenta de manera segura els desmuntatges temporals del chroot. Si un punt continua ocupat, mostra el procés responsable mitjançant `fuser`, sense usar desmuntatges forçats, recursius ni diferits.

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

El constructor munta temporalment `/dev`, `/proc`, `/sys` i `/run` dins del
rootfs. Els muntatges recursius es converteixen immediatament en `rslave`, de
manera que cap desmuntatge efectuat sota el chroot es pot propagar a l’arbre de
muntatges compartit de l’amfitrió.

Abans de desmuntar, el constructor detecta i finalitza únicament els processos
que tenen `root`, `cwd` o executable dins de `.build/production/rootfs`. Després
llegeix `/proc/self/mountinfo`, filtra estrictament els punts situats sota els
quatre arbres temporals del rootfs i els desmunta de més profund a menys profund.
No utilitza `umount -R`, `umount -l` ni desmuntatges forçats. Els errors `EBUSY`
es reintenten després de `sync` i, si persisteixen, es mostren diagnòstics amb
`fuser`.

El llançador conserva el codi d’eixida original, tracta `INT` i `TERM`
explícitament i executa sempre la neteja confinada. Això permet repetir:

```bash
./scripts/build-production-iso.sh --clean
```

sense deixar muntatges residuals ni afectar `/dev/pts` de la màquina
constructora.

### Arquitectura Live, usuaris i consoles

XAAC Thin Client OS conserva `live-boot` només per localitzar i muntar
`filesystem.squashfs`. `live-config` ja no forma part dels paquets obligatoris,
no s’executa i no participa en la creació d’usuaris, la localització ni
l’autologin.

Les entrades GRUB no contenen `components`, `username=`, `user-fullname=`,
`live-config.nocomponents` ni `live-config.nottyautologin`. El compte
`xaac-kiosk` es crea durant la fase `configure`, directament dins del rootfs,
amb shell de sessió vàlid i contrasenya bloquejada.

La política de consoles és íntegrament de XAAC:

- `tty1` disposa d’un únic drop-in d’autologin per a `xaac-kiosk`;
- `tty2`–`tty6` utilitzen sense modificacions la plantilla autenticada
  `getty@.service` de Debian;
- en mode instal·lador, `xaac-installer-welcome.service` pren exclusivament
  `tty1`, entra en conflicte amb `getty@tty1.service` i el restaura mitjançant
  `OnFailure` si l’instal·lador falla.

El bootstrap es fa en dues etapes: `debootstrap --variant=minbase` crea Debian
base i la fase `configure` instal·la kernel, firmware i paquets des de dins del
chroot.

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
`Install XAAC Thin Client OS` arranca amb `boot=live`, `xaac.mode=installer` i
`systemd.unit=multi-user.target`, sense cap paràmetre de `live-config`. `tty1`
és reservada per a l’instal·lador, mentre que `tty2`–`tty6` conserven el `getty`
estàndard autenticat de Debian.

`systemd.unit=multi-user.target`, inicia `xaac-installer-welcome.service` sobre
`tty1` i mostra una pantalla de benvinguda. En aquest pas no es detecten,
particionen, formaten ni modifiquen discs. En prémer Retorn, el sistema es
reinicia. L’opció `XAAC diagnostics (read-only)` manté el comportament Live.

Aquesta fita només valida el menú de GRUB, el paràmetre d’arrencada i el servei
de consola abans d’afegir cap operació destructiva.


### Instal·lador incremental — pas 2

L’opció d’instal·lació detecta els discs escrivibles, mostra dispositiu, mida i model i permet seleccionar-ne un. Aquest pas és estrictament no destructiu: no particiona, no formata ni escriu cap dada.

### Instal·lador incremental — pas 3

Després de seleccionar el disc, l’instal·lador torna a comprovar que el dispositiu
existeix i conserva la mateixa capacitat detectada. Rebutja destinacions menors de
7.000.000.000 bytes i qualsevol disc que tinga ell mateix o alguna partició
muntada. Els dispositius extraïbles es mostren amb una advertència explícita.

Abans de continuar presenta un resum amb dispositiu, capacitat i model, i exigeix
la frase exacta `INSTALL XAAC`. Una confirmació diferent cancel·la el procés. La
fase continua sent deliberadament no destructiva: encara no executa `sgdisk`,
`mkfs`, `dd` ni cap altra ordre d’escriptura.

### Instal·lador incremental — pas 4

Aquesta iteració agrupa la primera unitat destructiva completa de l’instal·lador.
Després de repetir les validacions del pas 3 i exigir `INSTALL XAAC`, comprova que
la destinació no és el dispositiu que conté el sistema Live actiu i valida
l’alimentació externa quan el maquinari l’exposa mitjançant `power_supply`.

L’instal·lador crea una taula GPT amb les particions `XAAC_EFI` (256 MiB),
`XAAC_ROOT` (4096 MiB), `XAAC_DATA` (1024 MiB) i `XAAC_RECOVERY` (espai restant),
les formata, les munta sota `/mnt/xaac-target`, desplega
`/run/live/medium/live/filesystem.squashfs` amb `unsquashfs` i genera un
`/etc/fstab` basat en UUID. Un `trap` sincronitza i desmunta en ordre invers en
cas d’èxit, error o interrupció.

Aquest pas encara no instal·la GRUB ni executa la postinstal·lació; per tant, el
disc queda amb el sistema base desplegat però encara no és arrancable de manera
autònoma.


### Instal·lador incremental — pas 5, estabilització UEFI

Aquesta fase completa la instal·lació arrancable i reforça el fallback UEFI. Després del desplegament del rootfs, l’instal·lador munta de manera confinada `/dev`, `/proc`, `/sys` i `/run`, executa `grub-install` amb `--removable --no-nvram` i genera `/boot/grub/grub.cfg`.

Per evitar que un firmware OVMF o el Dell Wyse rebutge un carregador EFI no signat, el fallback final usa la cadena signada de Debian:

- `EFI/BOOT/BOOTX64.EFI`: `shimx64.efi.signed`;
- `EFI/BOOT/grubx64.efi`: `grubx64.efi.signed`;
- `EFI/BOOT/grub.cfg`: localitza la partició arrel pel seu UUID i carrega `/boot/grub/grub.cfg`.

Abans de declarar l’èxit, l’instal·lador comprova que els executables tenen capçalera PE/COFF, que la primera partició és una ESP GPT `EF00`, que el FAT32 supera `fsck.vfat -n` i que el fitxer de fallback referencia l’UUID correcte. La postinstal·lació buida `machine-id`, elimina les claus SSH i la llavor aleatòria, marca el primer arrencament, desactiva l’instal·lador en el sistema desplegat i desa un resum en `/recovery/installer/installation-summary.txt`.

### Contrasenya de l’administrador durant la instal·lació

Després de la confirmació destructiva i abans de modificar el disc, l’instal·lador
demana dues vegades una contrasenya per a `xaac-admin`. L’entrada no es mostra a
la consola, ha de tindre almenys 12 caràcters i no pot contindre `:`. Només si
les dues entrades coincideixen continua la instal·lació.

La contrasenya s’aplica al sistema desplegat mitjançant `chpasswd`; després el compte es desbloqueja explícitament amb `usermod --unlock`, es fixa `/bin/bash` com a shell i s’eliminen caducitats residuals amb `chage`. Se’n comprova
l’estat amb `passwd -S`, el camp real de `/etc/shadow` i la shell efectiva i mai no s’escriu en fitxers, arguments de procés, logs ni
el resum de la instal·lació. `xaac-kiosk` continua bloquejat i reservat a
l’autologin de `tty1`; `root` continua sense accés interactiu per contrasenya.
Com que la contrasenya la tria directament l’administrador durant la instal·lació,
es crea el marcador de canvi completat i no es torna a exigir un canvi redundant
en el primer inici de sessió.

### Validació real de la contrasenya administrativa

La instal·lació no considera vàlida la configuració de `xaac-admin` només perquè `/etc/shadow` continga un hash. La contrasenya introduïda es transforma en un hash SHA-512, s’assigna explícitament al compte i es comprova immediatament contra la pila PAM de `login` amb `pamtester`. Si PAM no l’accepta, la instal·lació s’atura i no mostra el missatge d’èxit.

## Diagnòstic local en builds de desenvolupament

Quan `config/build.yaml` defineix `channel: development`, la imatge incorpora una eina de diagnòstic de només lectura. No afegeix entrades a GRUB ni canvia el procés d'arrencada. Des de la sessió automàtica de `xaac-kiosk` en `tty1` es pot executar:

```bash
sudo /usr/local/libexec/xaac/diagnostics
```

La regla de `sudoers` només autoritza aquest executable concret i no concedeix `sudo` general ni una shell de `root`. L'informe identifica primer si s'executa sobre el sistema `LIVE` o `INSTALLED`, mostra el dispositiu i el tipus del sistema de fitxers arrel, els UUID de l'arrel i de l'ESP, i resumeix l'estat de GRUB i dels executables UEFI. També mostra les entrades Linux detectades, l'estat segur de `xaac-kiosk` i `xaac-admin`, les dades de caducitat, la pila PAM i l'estat dels serveis principals (`display-manager`, `getty@tty1`, `getty@tty2`, `ssh` i l'instal·lador). Mai imprimeix cap hash complet ni modifica el sistema.

Per provar la contrasenya introduïda durant la instal·lació contra la mateixa pila PAM usada per `login`:

```bash
sudo /usr/local/libexec/xaac/diagnostics --pam-test
```

La contrasenya es demana interactivament i no es desa. Aquesta infraestructura no s'instal·la en canals `testing`, `candidate`, `stable` o `long-term`.

### Verificació reforçada de credencials d’administració

L’instal·lador escriu el hash xifrat de `xaac-admin` amb `chpasswd --encrypted`, comprova que el valor exacte ha quedat en l’`/etc/shadow` del disc de destinació i repeteix la comprovació al final de la postinstal·lació. El diagnòstic de desenvolupament mostra només informació segura i busca directives XAAC que pogueren tornar a bloquejar el compte.

## Arrencada
### Identitat del menú GRUB

El sistema instal·lat genera una entrada principal amb el nom exacte **XAAC Thin Client OS**. La configuració es manté en `/etc/default/grub.d/10-xaac-identity.cfg` i `/etc/grub.d/09_xaac`; no es modifica manualment el fitxer generat `/boot/grub/grub.cfg`.

 del sistema instal·lat

El rootfs comprimit exclou `/boot` per no duplicar el nucli dins de la ISO. Durant la instal·lació, el constructor copia explícitament `live/vmlinuz` i `live/initrd.img` al `/boot` del disc amb la versió detectada en `/lib/modules`, crea els enllaços estàndard i només accepta el `grub.cfg` si conté una entrada Linux completa.


## Consolidació de la instal·lació

La fase final de l’instal·lador elimina tots els artefactes exclusius del medi Live, fixa la identitat visible com a **XAAC Thin Client OS**, prepara una identitat nova per al primer arrencament i crea `/var/lib/xaac/installation/consolidated`. La instal·lació no es declara completada si l’instal·lador continua habilitat o si la identitat del sistema no és coherent.

### Hostname i xarxa durant la instal·lació

L’instal·lador demana un hostname, amb `xaac-thin-client` com a valor per defecte, i configura automàticament la xarxa Ethernet per DHCP.

### Eines i diagnòstic de xarxa

El sistema inclou `iproute2` i `iputils-ping`. La IP assignada per DHCP es pot consultar amb:

```bash
ip -4 addr show scope global
```

També es pot consultar l’estat complet de NetworkManager amb:

```bash
nmcli device status
nmcli device show
```

En builds de desenvolupament, `sudo /usr/local/libexec/xaac/diagnostics` incorpora una secció `network state` amb interfícies, adreces, passarel·la, DNS, connexions actives i rutes, sense modificar la configuració.

### Bloc 5 — arrencada definitiva del quiosc

El sistema instal·lat reserva `tty1` per a `greetd`, inicia la sessió `xaac-kiosk` sense shell interactiva i usa `graphical.target` com a target predeterminat. L'instal·lador accepta hostnames amb majúscules i la imatge inclou obligatòriament la família tipogràfica Roboto.

### Garantia de codi font del constructor

`./scripts/build-production-iso.sh` força la importació de `xaac_thin_client_os` des de `src/` del checkout actual i valida la ruta del mòdul abans de començar. D'aquesta manera una `.venv` antiga no pot produir silenciosament una ISO amb un constructor diferent del que s'està provant i revisant.

#### Runtime de la sessió de quiosc
Els fitxers efímers de la sessió (`flock`, estat del supervisor i socket Wayland) es resolen a partir de `XDG_RUNTIME_DIR`, que en systemd/logind és `/run/user/<UID>`. No s'utilitzen rutes basades en el nom `xaac-kiosk` sota `/run/user`.
