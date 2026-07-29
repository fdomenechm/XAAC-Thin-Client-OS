# XAAC Thin Client OS

XAAC Thin Client OS és una distribució especialitzada basada en Debian 13, orientada
principalment al Dell Wyse 3040 amb 2 GB de RAM i 8 GB d'eMMC. El sistema integrarà
XAAC Thin Client, XAAC Thin Client Agent i un client RustDesk personalitzat en una
sessió gràfica segura en mode quiosc.

## Estat actual

**Fase 3.1 — Inventari de maquinari Dell Wyse 3040**

Les fases 1.1 i 1.2 estableixen:

- projecte Python 3.13;
- estructura `src/`;
- entorn virtual local `.venv`;
- configuració de PyCharm;
- metadades en `pyproject.toml`;
- proves inicials amb `pytest`;
- scripts operatius i `Makefile` per normalitzar el desenvolupament;
- comprovació de la versió de Python;
- estructura inicial dels futurs components del constructor i del sistema;
- configuració YAML tipada per a build, paquets, repositoris i perfils;
- validació creuada del perfil Dell Wyse 3040.


## Fase 3.2 — Suport d’eMMC

El projecte detecta i valida dispositius eMMC `mmcblkN`, comprova capacitat, sector, tipus, controladors i suport TRIM, i prepara el rootfs amb els mòduls necessaris i `fstrim.timer`.

```bash
.venv/bin/xaac-os --root . inspect-emmc
.venv/bin/xaac-os --root . configure-emmc --dry-run
```

Consulteu `docs/development/PHASE_3_2.md`.

## Fase 3.1 — Inventari de maquinari

El sistema incorpora un perfil formal del Dell Wyse 3040 i l'ordre `inspect-hardware`
per detectar i comparar CPU, RAM, eMMC, gràfics, xarxa, àudio, USB, UEFI i sensors.
Consulteu `docs/development/PHASE_3_1.md`.

## Requisits de desenvolupament

- Python 3.13
- PyCharm
- Git

No s'admet Python 3.12 ni Python 3.14. La restricció queda declarada en
`pyproject.toml` com `>=3.13,<3.14`.

## Preparació de l'entorn

La via recomanada és:

```bash
./scripts/create-venv.sh
```

Aquesta ordre crea `.venv`, comprova Python 3.13 i instal·la el projecte amb les
dependències de desenvolupament. Per actualitzar una `.venv` existent:

```bash
./scripts/install-dev.sh
```

En PyCharm cal seleccionar l'intèrpret existent:

```text
<projecte>/.venv/bin/python
```

## Execució de les proves

```bash
./scripts/run-tests.sh
```

Amb cobertura i informe HTML en `htmlcov/`:

```bash
./scripts/run-coverage.sh
```

Validació estàtica:

```bash
./scripts/run-lint.sh
```

També es poden utilitzar les ordres equivalents del `Makefile`:

```bash
make test
make coverage
make lint
make build
make all
```

## Comprovació inicial

```bash
.venv/bin/python -m xaac_thin_client_os
.venv/bin/xaac-os version
```

## Estructura

```text
src/                         codi Python
tests/                       proves automatitzades
 builder/                     constructor d'imatges
 profiles/                    perfils de maquinari
 packages/                    paquets Debian propis
 config/                      configuracions del sistema
 recovery/                    recuperació
 docs/                        documentació
 tools/                       utilitats de desenvolupament
 scripts/                     scripts operatius del projecte
 Makefile                     accessos ràpids a les operacions habituals
```

## Llicència

GNU General Public License v3.0 o posterior.

## Configuració del constructor

La configuració declarativa inicial es troba en `config/*.yaml` i `profiles/*/profile.yaml`. Consulteu `docs/development/PHASE_1_2.md`.


## CLI del constructor

```bash
.venv/bin/xaac-os --root . validate
.venv/bin/xaac-os --root . inspect
.venv/bin/xaac-os --root . prepare
.venv/bin/xaac-os --root . build
```

Consulteu `docs/development/PHASE_1_3.md`.

## Espai de treball de construcció

Prepareu una execució aïllada amb:

```bash
./scripts/build.sh
# o bé
.venv/bin/xaac-os --root . prepare
```

Els artefactes temporals es creen exclusivament dins de `.build/runs/<build-id>`.


## Resolució de paquets

La configuració efectiva de paquets es calcula combinant els grups de `config/packages.yaml` amb la cadena d’herència del perfil seleccionat. Les exclusions tenen prioritat, els duplicats s’eliminen i el resultat és estable i reproduïble.

```bash
.venv/bin/xaac-os --root . inspect
.venv/bin/xaac-os --root . --json inspect
```

## Plantilles del sistema

Les plantilles declaratives resideixen en `templates/base/`. En executar:

```bash
.venv/bin/xaac-os --root . prepare
```

els fitxers es renderitzen de manera segura en `.build/runs/<build-id>/rendered/`.

## Hooks de construcció

Els hooks opcionals es poden afegir en `hooks/pre-bootstrap`, `post-bootstrap`,
`pre-packages`, `post-packages`, `pre-image` i `post-image`. Han de tindre permís
d'execució i la seua eixida queda registrada dins de l'espai de treball.


## Manifest de construcció

Cada `prepare` o `build` crea un manifest verificable amb la traçabilitat completa de la construcció. Consulteu `docs/development/PHASE_1_8.md`.


## Bootstrap Debian 13 minimal

Validació segura del pla:

```bash
.venv/bin/xaac-os --root . bootstrap --dry-run
```

Execució real amb privilegis:

```bash
sudo .venv/bin/xaac-os --root . bootstrap
```

Consulteu `docs/development/PHASE_2_1.md`.


## Configuració APT del rootfs

Després del bootstrap, valideu el pla sense modificar el sistema:

```bash
.venv/bin/xaac-os --root . configure-apt --dry-run
```

Execució real:

```bash
sudo .venv/bin/xaac-os --root . configure-apt
```

Consulteu `docs/development/PHASE_2_2.md`.


## Instal·lació del sistema base

Planificació segura:

```bash
.venv/bin/xaac-os --root . install-packages --dry-run
```

Execució real després de configurar APT:

```bash
sudo .venv/bin/xaac-os --root . install-packages
```

Consulteu `docs/development/PHASE_2_3.md`.


## Configuració d’identitat i paràmetres regionals

Planificació segura:

```bash
.venv/bin/xaac-os --root . configure-system --dry-run
```

Execució real després d’instal·lar el sistema base:

```bash
sudo .venv/bin/xaac-os --root . configure-system
```

La configuració declarativa resideix en `config/system.yaml` i defineix el nom
d’host, la zona horària i les locales generades. Consulteu
`docs/development/PHASE_2_4.md`.


## Configuració d’usuaris i grups inicials

Planificació segura:

```bash
.venv/bin/xaac-os --root . configure-users --dry-run
```

Execució real després de configurar el sistema:

```bash
sudo .venv/bin/xaac-os --root . configure-users
```

Els comptes `xaac-admin` i `xaac-kiosk` es creen bloquejats i sense secrets
inclosos al repositori. Consulteu `docs/development/PHASE_2_5.md`.


## Configuració de xarxa mínima

Planificació segura:

```bash
.venv/bin/xaac-os --root . configure-network --dry-run
```

Execució real després de configurar els usuaris:

```bash
sudo .venv/bin/xaac-os --root . configure-network
```

La configuració declarativa resideix en `config/network.yaml` i utilitza
`systemd-networkd` i `systemd-resolved`. Consulteu
`docs/development/PHASE_2_6.md`.


## Configuració del servidor SSH

Planificació segura:

```bash
.venv/bin/xaac-os --root . configure-ssh --dry-run
```

Execució real després de configurar la xarxa:

```bash
sudo .venv/bin/xaac-os --root . configure-ssh
sudo .venv/bin/xaac-os --root . configure-firewall
```

L'accés queda limitat a `xaac-admin` amb clau pública. Les xarxes autoritzades
es declaren en `config/ssh.yaml` i seran aplicades efectivament per la fase de
tallafoc. Consulteu `docs/development/PHASE_2_7.md`.


### Tallafoc base

```bash
.venv/bin/xaac-os --root . configure-firewall --dry-run
sudo .venv/bin/xaac-os --root . configure-firewall
```

## Fase actual: 2.3 - Kernel i initramfs

El projecte torna a seguir la numeració del calendari de desenvolupament 1.0. Després de `bootstrap`, `configure-apt` i `install-packages`, el kernel i l'initramfs es preparen amb:

```bash
.venv/bin/xaac-os --root . configure-kernel --dry-run
sudo .venv/bin/xaac-os --root . configure-kernel
```

Consulteu `docs/development/PHASE_2_3.md` i `docs/development/ROADMAP_ALIGNMENT.md`.


## Fase 2.6 — Sistema base systemd

Planificació segura:

```bash
.venv/bin/xaac-os --root . configure-systemd --dry-run
```

Execució real:

```bash
sudo .venv/bin/xaac-os --root . configure-systemd
```

Configura `multi-user.target`, consola temporal, límits de journald, tmpfiles, timers essencials i serveis habilitats, deshabilitats o emmascarats. Consulteu `docs/development/PHASE_2_6.md`.

## Fase 2.5 — Esquema inicial de particions

El constructor pot planificar i aplicar un esquema GPT segur per a 8 GB:

```bash
.venv/bin/xaac-os --root . configure-partitions --device /dev/mmcblk0 --dry-run
```

L'execució real exigeix `sudo` i `--confirm-destructive`. Consulteu `docs/development/PHASE_2_5.md`.

## Fase actual

La Fase 2.7 configura la localització i consola del sistema base mitjançant `config/localization.yaml` i l'ordre `configure-localization`. Consulteu `docs/development/PHASE_2_7.md`.


## Primera imatge arrencable

Després de completar el rootfs i les fases 2.1–2.7, es pot planificar o generar la primera imatge:

```bash
.venv/bin/xaac-os --root . build-image --dry-run
sudo .venv/bin/xaac-os --root . build-image
```

`build-image` és autocontinguda: si no existeix un rootfs complet en l’espai de treball actual, crea una construcció nova i executa en el mateix `build-id` el bootstrap, APT, paquets, configuració base, kernel/initramfs, systemd, localització, `fstab`, UEFI i assemblatge final. No cal executar manualment les fases anteriors.

El resultat inclou la imatge `.img`, una còpia `.img.gz`, hashes SHA-256 i el manifest actualitzat. Consulteu `docs/development/PHASE_2_8.md`.

### Dependències del sistema constructor

Abans de generar una imatge real en Debian, Ubuntu o Zorin OS, instal·leu totes les eines requerides amb:

```bash
./scripts/install-build-dependencies.sh
```

`build-image` comprova conjuntament totes les ordres necessàries abans de crear el workspace. Si en falta alguna, mostra la llista completa i no inicia una construcció parcial. El mode `--dry-run` continua sent offline i no exigeix aquestes eines.

## Fase 3.3 — Gràfics Intel

La GPU Intel i915, els connectors DisplayPort i els modes disponibles es poden inspeccionar amb:

```bash
.venv/bin/xaac-os --root . inspect-graphics
.venv/bin/xaac-os --root . inspect-graphics --report reports/graphics.json
```

La configuració del rootfs es pot planificar i aplicar amb:

```bash
.venv/bin/xaac-os --root . configure-graphics --dry-run
sudo .venv/bin/xaac-os --root . configure-graphics
```

Consulteu `docs/development/PHASE_3_3.md`.

## Fase 3.4 — Xarxa Ethernet

El perfil del Dell Wyse 3040 incorpora detecció i validació de la interfície Ethernet, controlador, portadora, velocitat, dúplex i Wake-on-LAN:

```bash
.venv/bin/xaac-os --root . inspect-ethernet
.venv/bin/xaac-os --root . inspect-ethernet --report reports/ethernet.json
```

La configuració del rootfs utilitza `systemd-networkd`, DHCPv4 per defecte i admet IPv4 estàtica validada:

```bash
.venv/bin/xaac-os --root . configure-ethernet --dry-run
.venv/bin/xaac-os --root . configure-ethernet --mode static \
  --address 192.0.2.10/24 --gateway 192.0.2.1 --dns 192.0.2.53
```

Consulteu `docs/development/PHASE_3_4.md`.


## Fase 3.5 — Àudio

El perfil del Dell Wyse 3040 incorpora detecció i validació de targetes ALSA, mòduls del kernel, eixides HDMI/DisplayPort, jack analògic, micròfon i disponibilitat de PipeWire.

```bash
.venv/bin/xaac-os --root . inspect-audio
.venv/bin/xaac-os --root . --json inspect-audio
.venv/bin/xaac-os --root . inspect-audio --report reports/audio.json
.venv/bin/xaac-os --root . configure-audio --dry-run
.venv/bin/xaac-os --root . configure-audio
```

La configuració genera fitxers deterministes per carregar els mòduls ALSA, aplicar l'estalvi energètic del controlador HDA i definir la selecció automàtica d'entrada i eixida mitjançant PipeWire. Consulteu `docs/development/PHASE_3_5.md`.


## Fase 3.6 — USB i perifèrics

La inspecció del maquinari USB identifica controladors USB 2.0/3.x i classifica dispositius HID, emmagatzematge, smartcard, impressores i càmeres a partir de sysfs, incloent VID/PID i estat d'autorització.

```bash
.venv/bin/xaac-os --root . inspect-usb
.venv/bin/xaac-os --root . --json inspect-usb
.venv/bin/xaac-os --root . inspect-usb --report reports/usb.json
.venv/bin/xaac-os --root . configure-usb --dry-run
.venv/bin/xaac-os --root . configure-usb
```

La configuració genera una política declarativa XAAC, regles udev deterministes i la càrrega dels mòduls necessaris. La política registra els tipus aptes per a redirecció FreeRDP sense activar-la encara, ja que la integració efectiva correspon als blocs de sessió gràfica i XAAC. Consulteu `docs/development/PHASE_3_6.md`.

## Fase 3.7 — Energia i temperatura

```bash
.venv/bin/xaac-os --root . inspect-power
.venv/bin/xaac-os --root . inspect-power --report reports/power.json
.venv/bin/xaac-os --root . configure-power --dry-run
.venv/bin/xaac-os --root . configure-power
```

La configuració desactiva suspensió i hibernació, defineix el watchdog i registra els llindars tèrmics. El comportament després d'una pèrdua de corrent depén del firmware i es valida sobre maquinari real. Consulteu `docs/development/PHASE_3_7.md`.

### Optimització del Dell Wyse 3040

La Fase 3.8 incorpora zram, límits de journald, `/tmp` en tmpfs, política `noatime` i neteja automàtica. La configuració es pot inspeccionar i aplicar amb `inspect-resources` i `configure-resources`. Consulteu `docs/development/PHASE_3_8.md`.

### Compositor mínim

```bash
xaac-os configure-compositor --dry-run
xaac-os configure-compositor
```

Vegeu `docs/development/PHASE_4_2.md`.

### Gestor de sessió gràfica

La fase 4.3 incorpora `greetd` amb autologin exclusiu de `xaac-kiosk` i una sessió Wayland dedicada basada en `labwc`. Es configura amb `xaac-os configure-session-manager`.


La fase 4.4 incorpora la configuració declarativa del compte dedicat `xaac-kiosk`.

### Llançament de XAAC Thin Client

```bash
xaac-os configure-thin-client-launcher --dry-run
xaac-os configure-thin-client-launcher
```

### Fase 4.6 — Supervisió de la sessió

La sessió gràfica inicia `xaac-session-supervisor`, que manté XAAC Thin Client disponible amb reinicis limitats, backoff exponencial, estat runtime, pantalla d'error segura i notificació local preparada per a l'Agent.


## Fase 4.7 — Multimonitor i escalat

La sessió XAAC disposa d’una política multimonitor amb Wayland principal, fallback X11, escalat mixt, hotplug i integració FreeRDP. Consulteu `docs/development/PHASE_4_7.md`.

## Validació de la sessió gràfica

La fase 4.8 incorpora la validació completa del bloc de sessió gràfica:

```bash
xaac-os validate-graphical-session --dry-run
xaac-os validate-graphical-session
```

La política verifica l'arrencada dedicada, el consum, l'estabilitat i l'absència d'escriptoris i terminals convencionals.


## Fase 5.1 — Model de restriccions del quiosc

La política `config/kiosk-restrictions.yaml` defineix amenaces, accions autoritzades, dreceres, processos, dispositius i sessions amb denegació per defecte.

```bash
xaac-os configure-kiosk-restrictions --dry-run
xaac-os configure-kiosk-restrictions
```

L’enforcement resta en mode `staged` fins que les fases 5.2–5.7 implementen cada control. Consulteu `docs/development/PHASE_5_1.md`.

## Fase 5.2 — Bloqueig de dreceres

La política `config/shortcut-lockdown.yaml` aplica denegació per defecte a les dreceres de labwc i Openbox i elimina les combinacions predeterminades dels dos backends.

```bash
xaac-os configure-shortcut-lockdown --dry-run
xaac-os configure-shortcut-lockdown
```

Es bloquegen el canvi d’aplicació, el tancament de finestres, els menús, els llançadors, les captures i les dreceres de sistema. `Ctrl+Alt+F12` queda reservada per al TTY administratiu que es definirà en la Fase 5.4. Consulteu `docs/development/PHASE_5_2.md`.

## Fase 5.3 — Bloqueig de terminals

La sessió `xaac-kiosk` no incorpora emuladors de terminal i aplica una política de denegació per defecte per a ordres, llançadors i URI. El `PATH` de la sessió queda reduït a `/usr/local/libexec/xaac:/usr/libexec/xaac`, els esquemes URI no autoritzats es dirigeixen a un manejador deshabilitat i no es permeten fitxers `.desktop` creats per l’usuari.

```bash
xaac-os configure-terminal-lockdown --dry-run
xaac-os configure-terminal-lockdown
```

La configuració efectiva es genera en `/etc/xaac/kiosk/environment.d/20-terminal-lockdown.conf`, `/etc/xaac/kiosk/mimeapps.list` i `/etc/xaac/kiosk/terminal-lockdown.json`.

## Fase 5.4 — Control dels TTY

Els TTY 1–11 queden deshabilitats per a l'usuari final. `tty12` es reserva com a consola administrativa local, restringida a `xaac-admin` i protegida per autenticació.

```bash
xaac-os configure-tty-control --dry-run
xaac-os configure-tty-control
```

La configuració desactiva els VT automàtics de `systemd-logind`, emmascara els `getty` i `autovt` no autoritzats i genera una política auditable en `/etc/xaac/kiosk/tty-control.json`. El compte administrador continua bloquejat fins a la seua activació controlada en la Fase 7.6. Consulteu `docs/development/PHASE_5_4.md`.

## Fase 5.5 — Sistema de fitxers del quiosc

La sessió `xaac-kiosk` utilitza un `home` efímer sobre `tmpfs`, amb directoris permesos mínims, descàrregues no executables, permisos `0077` i neteja automàtica entre sessions.

```bash
xaac-os configure-kiosk-filesystem --dry-run
xaac-os configure-kiosk-filesystem
```

Consulteu `docs/development/PHASE_5_5.md`.

## Fase 5.6 — Control de dispositius locals

La sessió de quiosc aplica una política de denegació per defecte als dispositius USB i bloqueja l'emmagatzematge extraïble i l'automuntatge. Smartcards i impressores poden continuar autoritzades per política, mentre que les càmeres queden deshabilitades per defecte.

```bash
xaac-os configure-local-device-control --dry-run
xaac-os configure-local-device-control
```

Consulteu `docs/development/PHASE_5_6.md`.

## Fase 5.7 — Control d’apagada i reinici

El mode quiosc no pot executar directament accions d’energia. Apagada i reinici es tramiten com a peticions confirmades a XAAC Agent, mentre que suspensió i hibernació romanen bloquejades. Les tecles físiques d’energia són ignorades per `systemd-logind` i Polkit denega les accions directes de `xaac-kiosk`.

```bash
xaac-os configure-power-action-control --dry-run
xaac-os configure-power-action-control
```

Consulteu `docs/development/PHASE_5_7.md`.

### Servei de primer inici

La fase 6.4 incorpora `xaac-first-boot.service`, que valida el maquinari i inicialitza la identitat persistent abans de l'Agent i de la sessió gràfica. La configuració es prepara amb `xaac-os --root . configure-first-boot`. Consulteu `docs/PHASE_6_4.md`.

### IPC Client-Agent

La fase 6.5 configura un socket Unix privat i versionat entre XAAC Thin Client i XAAC Agent. L'accés queda restringit al grup `xaac-ipc`, l'Agent ha de verificar `SO_PEERCRED` i només s'accepten els tipus de missatge declarats.

```bash
xaac-os --root . configure-ipc --dry-run
xaac-os --root . configure-ipc
```

Consulteu `docs/PHASE_6_5.md`.

### Aplicació de polítiques

La fase 6.6 incorpora el motor transaccional de polítiques del dispositiu. Les polítiques es validen per esquema, seccions, mida i digest SHA-256 abans de passar a staging. L'aplicació conserva la revisió anterior, exigeix confirmació i permet rollback segur.

```bash
xaac-os --root . configure-policy-application --dry-run
xaac-os --root . configure-policy-application
```

Consulteu `docs/PHASE_6_6.md`.

### Inventari del dispositiu

La fase 6.7 genera un inventari versionat de maquinari, sistema, paquets, perifèrics, versions XAAC i estat local. El document incorpora un digest SHA-256 i queda preparat perquè XAAC Agent l'envie posteriorment a XMS.

```bash
xaac-os --root . collect-device-inventory --dry-run
xaac-os --root . collect-device-inventory
```

Consulteu `docs/PHASE_6_7.md`.

### Integració XMS

La fase 6.8 incorpora el motor local d’enrolament segur en XMS:

```bash
xaac-os --root . configure-xms-enrollment --dry-run
xaac-os --root . configure-xms-enrollment
```

La configuració és a `config/xms-enrollment.yaml` i el detall funcional a `docs/PHASE_6_8.md`.

## Configuració DHCP i IP estàtica — Fase 7.2

El sistema utilitza `systemd-networkd` i aplica perfils IPv4 validats de manera transaccional:

```bash
.venv/bin/xaac-os --root . configure-ip-addressing --mode dhcp --dry-run
.venv/bin/xaac-os --root . configure-ip-addressing --source remote --mode static \
  --address 192.0.2.10/24 --gateway 192.0.2.1 --dns 192.0.2.53 --dry-run
.venv/bin/xaac-os --root . configure-ip-addressing --rollback --dry-run
```

La configuració activa, l'estat per a l'Agent i els snapshots es generen dins del `rootfs` de construcció.

## DNS, NTP i proxy — Fase 7.3

```bash
.venv/bin/xaac-os --root . configure-network-services \
  --source remote --dns 192.0.2.53 --domain example.org \
  --ntp ntp.example.org --proxy http://proxy.example.org:3128 \
  --no-proxy localhost --no-proxy example.org --dry-run
.venv/bin/xaac-os --root . configure-network-services --rollback --dry-run
```

La configuració utilitza `systemd-resolved` i `systemd-timesyncd`, genera configuració equivalent per a APT i publica estat i diagnòstic per a XAAC Agent. Consulteu `docs/PHASE_7_3.md`.

## VLAN 802.1Q — Fase 7.4

```bash
.venv/bin/xaac-os --root . configure-vlan --vlan-id 100 --mode dhcp --dry-run
.venv/bin/xaac-os --root . configure-vlan --source remote --vlan-id 200 \
  --mode static --address 192.0.2.10/24 --gateway 192.0.2.1 \
  --dns 192.0.2.53
.venv/bin/xaac-os --root . configure-vlan --vlan-id 200 --rollback
```

La configuració genera unitats persistents de `systemd-networkd`, publica estat i diagnòstic per a XAAC Agent i permet recuperar la connectivitat eliminant la VLAN i retornant a la interfície pare. Consulteu `docs/PHASE_7_4.md`.

### IEEE 802.1X (fase 7.5)

La configuració corporativa Ethernet admet EAP-TLS i PEAP/MSCHAPv2 amb `wpa_supplicant`, credencials protegides, estat per a XAAC Agent, renovació de certificats i rollback. Consulteu `docs/development/PHASE_7_5.md`.

### Perfil administrador local (fase 7.6)

El perfil `xaac-admin` disposa de canvi obligatori de contrasenya, `sudo` restringit, menú de consola i auditoria. Consulteu `docs/development/PHASE_7_6.md`.

## Fase 7.7 — OpenSSH restringit

La configuració `config/ssh.yaml` defineix l'accés administratiu per OpenSSH: només `xaac-admin`, claus públiques aprovades, xarxes corporatives autoritzades, reenviaments desactivats i activació temporal amb caducitat automàtica. Consulteu `docs/phase-7.7-openssh.md`.

## Fase 7.8 — Tallafoc nftables

La configuració `config/firewall.yaml` defineix el tallafoc persistent del dispositiu. Les cadenes `input` i `forward` utilitzen política `drop`; l'eixida es manté en `accept` per permetre que XAAC Agent, les actualitzacions i RustDesk inicien connexions cap als serveis corporatius.

El trànsit entrant de gestió només s'autoritza des de les xarxes declarades en `management.sources`. El port SSH es pren de `config/ssh.yaml`. Els ports entrants de XAAC Agent i RustDesk romanen tancats per defecte i només s'obrin quan la política corresponent activa el servei i declara ports TCP o UDP vàlids.

Planificació:

```bash
.venv/bin/xaac-os --root . configure-firewall --dry-run
```

Aplicació sobre el rootfs:

```bash
sudo .venv/bin/xaac-os --root . configure-firewall
```

L'aplicació genera `/etc/nftables.conf`, activa `nftables.service` i publica l'estat versionat en `/var/lib/xaac-agent/network/firewall.json`.

Amb aquesta fase queda tancat el **Bloc 7 — Xarxa i administració**.

## RustDesk XAAC — Fase 8.2

El branding controlat de **XAAC Remote Support** es defineix en `config/rustdesk-branding.yaml` i es genera amb:

```bash
xaac-os configure-rustdesk-branding
```

Aquesta fase instal·la nom, icona, logotip, textos, etiquetes de servidor i informació de versió. Les adreces i claus dels servidors es configuraran en la fase 8.3.

## Configuració centralitzada de RustDesk — Fase 8.3

El perfil `config/rustdesk-central.yaml` centralitza els servidors ID i relay, la clau pública, el proxy, les polítiques de funcions remotes i el canal d'actualització de **XAAC Remote Support**. L'ordre `configure-rustdesk-central` aplica la configuració mitjançant staging i substitució atòmica; `rollback-rustdesk-central` restaura l'última còpia anterior. Els valors `.invalid` inclosos són deliberadament no operatius i s'han de substituir durant el desplegament.

### Fase 8.4 — Servei RustDesk

`xaac-os-build configure-rustdesk-service` instal·la la unitat systemd, l'usuari dedicat, els directoris temporals i l'estat auditable del servei XAAC Remote Support. El servei queda desactivat per defecte; l'activació temporal es desenvolupa en la fase 8.5.

### Fase 8.5 — Activació sota demanda

RustDesk continua desactivat per defecte. `configure-rustdesk-activation` instal·la la política, el helper i les unitats d'expiració. Una sessió temporal es pot autoritzar localment o des de XMS amb `activate-rustdesk-support`; la duració queda entre 5 i 240 minuts, el token és d'un sol ús i només se'n conserva el hash. `deactivate-rustdesk-support` tanca anticipadament la sessió. Consulteu `docs/PHASE_8_5.md`.

### Fase 8.6 — Consentiment

`configure-rustdesk-consent` instal·la la política de consentiment de XAAC Remote Support. El mode predeterminat requereix confirmació visible de l'usuari i permet aprovar, denegar o cancel·lar. L'accés `authorized-unattended` queda restringit a peticions XMS sobre dispositius gestionats amb autorització explícita de política. Consulteu `docs/PHASE_8_6.md`.

### Fase 8.7 — Auditoria de sessions

`configure-rustdesk-audit` instal·la l'estat d'auditoria. `start-rustdesk-audit` registra operador, dispositiu, motiu, origen i inici UTC; `end-rustdesk-audit` registra el final, l'estat i la duració en segons. El journal JSON Lines és append-only i només s'admet una sessió activa. Consulteu `docs/PHASE_8_7.md`.


### Fase 8.8 — Validació amb mode quiosc

`configure-rustdesk-kiosk-validation` instal·la la política i la llista de comprovacions. `validate-rustdesk-kiosk --evidence <fitxer.json>` avalua captura, entrada, multimonitor, Wayland/X11, bloqueig i rendiment, i publica l'informe per a XAAC Agent. Les proves que depenen d'una sessió gràfica o del Wyse 3040 requereixen evidència real. Consulteu `docs/PHASE_8_8.md`.

Amb aquesta fase queda tancat el **Bloc 8 — RustDesk personalitzat**.

## Fase 9.1 — Política de seguretat base

`config/security-policy.yaml` defineix el model d'amenaces, els actius, actors, superfícies, controls i riscos acceptats del sistema. L'ordre següent valida i instal·la la política dins del `rootfs`:

```bash
xaac-os --root . configure-security-policy --dry-run
xaac-os --root . configure-security-policy
```

La política operativa, el model documental i l'estat per a XAAC Agent es publiquen separadament. Consulteu `docs/PHASE_9_1.md`.


## Fase 9.2 — Usuaris i permisos

`config/account-permissions.yaml` consolida `root`, l'administrador local, el quiosc, XAAC Agent i RustDesk sota una política de mínim privilegi. Per validar-la i instal·lar-la:

```bash
xaac-os --root . configure-account-permissions --dry-run
xaac-os --root . configure-account-permissions
```

La configuració genera fragments `systemd-sysusers` i `systemd-tmpfiles`, la política auditable i l'estat per a XAAC Agent. Consulteu `docs/PHASE_9_2.md`.

## Fase 9.3 — Hardening systemd

La política `config/systemd-hardening.yaml` genera drop-ins de seguretat per als serveis XAAC amb privilegis, dispositius, namespaces, famílies d'adreces i syscalls mínims.

```bash
xaac-os --root . configure-systemd-hardening --dry-run
xaac-os --root . configure-systemd-hardening
```

Vegeu `docs/PHASE_9_3.md`.

## Fase 9.4 — AppArmor

`config/apparmor.yaml` defineix els perfils de confinament de XAAC Agent, XAAC Thin Client i XAAC Remote Support. Els dos primers s'instal·len en mode `enforce`; RustDesk queda en `complain` fins completar l'ajust amb maquinari i sessió reals.

```bash
xaac-os --root . configure-apparmor --dry-run
xaac-os --root . configure-apparmor
```

Vegeu `docs/PHASE_9_4.md`.

### Fase 9.5 — Hardening del kernel

`config/kernel-hardening.yaml` defineix els paràmetres `sysctl`, les restriccions de `ptrace`, ASLR, xarxa, core dumps, Magic SysRq i la política de mòduls del kernel. La configuració efectiva s'instal·la de manera idempotent i genera estat auditable per a XAAC Agent.

```bash
xaac-os --root . configure-kernel-hardening --dry-run
xaac-os --root . configure-kernel-hardening
```

### Fase 9.6 — Integritat de fitxers

La política `config/file-integrity.yaml` defineix els directoris crítics, les excepcions i les eixides del sistema d'integritat. La fase genera un manifest SHA-256, una baseline local protegida, un verificador i un temporitzador systemd.

```bash
xaac-os --root . configure-file-integrity --dry-run
xaac-os --root . configure-file-integrity
xaac-os --root . verify-file-integrity
xaac-os --root . verify-file-integrity --repair
```

La reparació restaura únicament fitxers inclosos en la baseline. Els fitxers dinàmics i temporals han de quedar coberts per patrons d'exclusió explícits.

### Fase 9.7 — Signatura de paquets

`config/package-signing.yaml` defineix el repositori XAAC, la clau activa, les claus anteriors de confiança, les revocacions i la verificació de paquets offline. La configuració força `Signed-By`, impedeix repositoris insegurs i instal·la un verificador de manifests signats.

```bash
xaac-os --root . configure-package-signing --dry-run
xaac-os --root . configure-package-signing
```

Les claus privades mai no s'inclouen en el projecte ni en la imatge. Consulteu `docs/PHASE_9_7.md`.

### Fase 9.8 — Secure Boot i TPM

```bash
xaac-os --root . configure-secure-boot-tpm --dry-run
xaac-os --root . configure-secure-boot-tpm
```

La imatge utilitza una cadena UEFI signada de Debian. Secure Boot s’activa quan el firmware del Wyse 3040 ho permet; TPM 2.0 és opcional i no bloqueja l’arrencada ni la recuperació. Consulteu `docs/PHASE_9_8.md`.

### Fase 10.1 — Model d’actualització

`config/update-model.yaml` defineix els components actualitzables, els canals, les finestres de manteniment, la política de versions i dependències i la màquina d’estats de l’actualització.

```bash
xaac-os --root . configure-update-model --dry-run
xaac-os --root . configure-update-model
```

La fase genera una política efectiva i l’estat inicial per a XAAC Agent, però no incorpora encara el repositori APT ni executa instal·lacions. Consulteu `docs/PHASE_10_1.md`.

### Fase 10.3 — Servei d’actualització

La configuració `config/update-service.yaml` defineix la comprovació periòdica, la descàrrega controlada i el staging previ a la verificació. La fase instal·la una unitat i un temporitzador systemd endurits, manté estat auditable, exigeix espai lliure mínim i evita execucions simultànies mitjançant un fitxer de bloqueig.

```bash
xaac-os-build configure-update-service --dry-run
xaac-os-build configure-update-service
```

La verificació criptogràfica i de compatibilitat del contingut staged s’implementarà en la fase 10.4.
### Fase 10.4 — Verificació d’actualitzacions

`config/update-verification.yaml` imposa la verificació fail-closed del contingut en staging: signatura OpenPGP, hashes SHA-256 i SHA-512, arquitectura, sistema operatiu, perfil `wyse3040`, versió mínima i dependències.

```bash
xaac-os-build configure-update-verification --dry-run
xaac-os-build configure-update-verification
```

La fase genera la política, l’estat auditable i el llançador restringit del verificador. No instal·la encara els paquets; la instal·lació transaccional correspon a la fase 10.5. Consulteu `docs/PHASE_10_4.md`.


### Fase 10.5 — Instal·lació transaccional

La instal·lació d’una actualització verificada es configura amb:

```bash
xaac-os-build configure-transactional-update
```

El procés exigeix un punt de recuperació, aplica conjunts atòmics, reinicia únicament serveis autoritzats, valida el sistema i només confirma la transacció després de superar totes les comprovacions. Davant una fallada, conserva evidències i inicia el rollback automàtic.

### Fase 10.6 — Rollback de paquets

El rollback segur d'una transacció fallida es configura amb:

```bash
xaac-os-build configure-package-rollback --dry-run
xaac-os-build configure-package-rollback
```

La política exigeix versions anteriors i un punt de recuperació, restaura paquets, configuració i estat, reinicia només serveis afectats, valida el resultat i bloqueja la versió defectuosa. Consulteu `docs/PHASE_10_6.md`.

### Fase 10.7 — Desplegament per anells

El desplegament progressiu d'actualitzacions es configura amb:

```bash
xaac-os-build configure-update-rings --dry-run
xaac-os-build configure-update-rings
```

La política defineix els anells `laboratory`, `pilot` i `production`, selecció determinista per percentatge, promoció manual seqüencial, períodes d'observació, llindars d'èxit i controls de pausa, represa i cancel·lació. Consulteu `docs/PHASE_10_7.md`.

### Fase 11.1 — Model d'estats de recuperació

`config/recovery-model.yaml` defineix les classes de fallada, comptadors, finestres, llindars, estats segurs, accions i notificacions de recuperació.

```bash
xaac-os --root . configure-recovery-model --dry-run
xaac-os --root . configure-recovery-model
```

El model és *fail-closed*, conserva evidències, notifica XAAC Agent i XMS en els estats crítics i prohibeix el `factory reset` automàtic. Consulteu `docs/PHASE_11_1.md`.

### Recuperació de l'aplicació (fase 11.2)

La recuperació del client i de la sessió de quiosc es configura amb:

```bash
xaac-os --root . configure-application-recovery --dry-run
xaac-os --root . configure-application-recovery
```

La política aplica recuperació escalonada, neteja únicament estat efímer, conserva diagnòstics i permet restaurar només una política anterior validada.

### Fase 11.3 — Reparació de paquets

La comprovació i reparació controlada de paquets es configura amb:

```bash
xaac-os --root . configure-package-repair --dry-run
xaac-os --root . configure-package-repair
```

La política audita `dpkg` i APT, verifica els fitxers instal·lats, reinstal·la només paquets gestionats des de repositoris signats, repara dependències, restaura configuració de manera atòmica i exigeix una validació final completa. Consulteu `docs/PHASE_11_3.md`.

### Fase 11.4 — Mode de recuperació local

El sistema pot instal·lar una entrada GRUB de recuperació, un target systemd mínim i un menú autenticat mitjançant `configure-local-recovery`.

### Fase 11.5 — Partició de recuperació

La partició local protegida, la verificació de la imatge signada i l'entrada GRUB associada es configuren amb:

```bash
xaac-os --root . configure-recovery-partition --dry-run
xaac-os --root . configure-recovery-partition
```

La partició es munta només en lectura i la verificació falla de manera segura si la imatge, la signatura, el kernel o l'initramfs no són coherents.

## Factory reset controlat

La fase 11.6 configura una restauració de fàbrica local amb:

```bash
xaac-os --root . configure-factory-reset --dry-run
xaac-os --root . configure-factory-reset
```

El procés exigeix administrador local, presència física i confirmació textual exacta; conserva la identitat i l'enrolament, restaura des de la partició signada i executa un primer inici auditable.
