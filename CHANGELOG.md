# Correcció estructural prèvia a la fase 11.1

- Afegits fitxers `README.md` als directoris estructurals que podien estar buits.
- Garantida la persistència en Git dels directoris `builder`, `hooks`, `recovery` i `tools`, inclosos els seus subdirectoris reservats.
- Afegida una prova de regressió que comprova l'existència dels README estructurals.

# Fase 10.7 — Desplegament per anells

- Afegits els anells ordenats `laboratory`, `pilot` i `production`.
- Incorporada selecció determinista de dispositius per percentatge basada en `device_uuid`.
- Exigida promoció seqüencial, èxit de l'anell anterior, observació mínima i aprovació manual.
- Afegits llindars d'èxit i fallada, pausa, represa i cancel·lació segura.
- Incorporats estat persistent, auditoria obligatòria, llançador i servei systemd endurit.
- Afegida l'ordre `configure-update-rings` amb mode `--dry-run`.
- Afegides 12 proves positives, negatives, d'idempotència, permisos, symlinks i CLI.

# Fase 10.4 — Verificació d’actualitzacions

- Afegida una política fail-closed per verificar actualitzacions preparades en staging.
- Fet obligatori validar la signatura OpenPGP del manifest amb el keyring XAAC.
- Exigits hashes SHA-256 i SHA-512 per a tots els artefactes.
- Incorporades comprovacions d’arquitectura, sistema, perfil Wyse 3040, versió mínima i bloqueig de downgrade.
- Incorporada validació de dependències declarades, cicles i conjunts atòmics.
- Generats política, estat auditable i llançador del verificador amb permisos restrictius.
- Afegida l’ordre `configure-update-verification` amb mode `--dry-run`.
- Afegides 12 proves positives, negatives, d’idempotència, permisos, symlinks i CLI.

# Fase 9.2 — Usuaris i permisos

- Consolidats els comptes `root`, `xaac-admin`, `xaac-kiosk`, `xaac-agent` i `xaac-rustdesk` sota una política única.
- Afegides regles de mínim privilegi, separació de funcions i bloqueig de login per a comptes no interactius.
- Declarats propietaris, grups i modes dels directoris sensibles.
- Generats fragments `systemd-sysusers` i `systemd-tmpfiles`, política JSON i estat per a XAAC Agent.
- Afegida l'ordre `configure-account-permissions` amb mode `--dry-run`.
- Afegides proves positives, negatives, de permisos, idempotència, symlinks i CLI.

# Fase 9.1 — Política de seguretat base

- Afegit el perfil declaratiu de seguretat amb objectius, actius, actors, superfícies, amenaces, controls i riscos acceptats.
- Incorporada validació estricta de nivells, identificadors i referències creuades.
- Generats la política operativa, el model d'amenaces i l'estat versionat per a XAAC Agent.
- Afegides escriptures atòmiques, permisos restrictius, idempotència i protecció de symlinks.
- Afegida l'ordre `configure-security-policy` amb mode `--dry-run`.
- Afegides proves positives, negatives, de permisos, idempotència, seguretat i CLI.

# Fase 8.8 — Validació de RustDesk amb mode quiosc

- Afegit el contracte declaratiu de validació de captura, entrada, multimonitor, Wayland/X11, bloqueig i rendiment.
- Incorporats política, checklist, informe i estat versionat per a XAAC Agent.
- Afegida validació d'evidència explícita amb llindars de recursos i latència.
- Evitat declarar com a superades les proves que requereixen sessió gràfica o maquinari real sense evidència.
- Afegides les ordres `configure-rustdesk-kiosk-validation` i `validate-rustdesk-kiosk`.
- Afegides proves positives, negatives, de permisos, symlinks, rendiment i CLI.
- Tancat el Bloc 8 — RustDesk personalitzat.

# Fase 8.3 — Configuració centralitzada de RustDesk XAAC

- Afegit el perfil declaratiu de servidors ID i relay, API, clau pública, proxy, polítiques i actualització.
- Implementades validacions estrictes d'endpoints, HTTPS, xifratge, proxy i rutes d'eixida.
- Incorporada aplicació transaccional amb staging, backup, substitució atòmica i rollback.
- Afegides proteccions contra symlinks, permisos `0640` i mode `--dry-run`.
- Afegides les ordres `configure-rustdesk-central` i `rollback-rustdesk-central`.
- Afegides proves positives, negatives, d'idempotència operativa, rollback, permisos i CLI.

# Fase 8.2 — Branding de RustDesk XAAC

- Definida la identitat **XAAC Remote Support** amb nom, application ID i desktop ID propis.
- Afegides icona i logotip SVG, entrada d'aplicació i entorn de branding.
- Incorporats textos, etiquetes de servidors gestionats i informació de versió.
- Afegit manifest auditable, escriptura atòmica, idempotència i protecció de symlinks.
- Afegida l'ordre `configure-rustdesk-branding` amb mode `--dry-run`.
- Afegides proves positives, negatives, de permisos lògics, idempotència i CLI.

# Fase 8.1 — Paquet RustDesk XAAC

- Afegit el perfil declaratiu d'origen, versió, arquitectura i dependències de RustDesk XAAC.
- Implementada la inspecció i validació segura del paquet Debian amb SHA-256 opcional.
- Incorporades instal·lació mínima, desinstal·lació completa, manifest auditable i protecció de symlinks.
- Afegides les ordres `install-rustdesk` i `uninstall-rustdesk` amb mode `--dry-run`.
- Afegides proves positives, negatives, d'idempotència operativa i seguretat.

# Fase 7.6 — Perfil administrador local

- Corregida la prova d’idempotència perquè substituïsca atòmicament el fitxer `sudoers` de prova amb permisos `0440`, evitant un `PermissionError` en entorns no executats com a root.
- Afegit el compte administratiu declarat `xaac-admin` amb home i grups mínims.
- Incorporats hash inicial segur i canvi obligatori de contrasenya.
- Afegida política `sudo` restringida i menú administratiu de consola.
- Incorporades regles d'auditoria, estat, snapshot, rollback i protecció de symlinks.
- Afegides proves positives, negatives, d'idempotència, permisos i CLI.

# Fase 7.4 — VLAN 802.1Q

- Afegit el perfil declaratiu `config/vlan.yaml` i l'ordre `configure-vlan`.
- Implementada la generació persistent de fitxers `.netdev` i `.network` per a `systemd-networkd`.
- Afegit adreçament DHCP o IPv4 estàtic, configuració local/remota i validació de polítiques.
- Incorporats estat, diagnòstic, staging, snapshot, rollback i fallback a la interfície pare.
- Afegides proves positives, negatives, d'idempotència, recuperació i CLI.

# Fase 7.1 — Gestor de xarxa

- Seleccionat `systemd-networkd` com a gestor de xarxa definitiu i exclusiu.
- Afegida configuració Ethernet base amb DHCP IPv4 i espera de connectivitat.
- Afegit manifest auditable i contracte d'estat versionat per a XAAC Agent.
- Afegit drop-in de systemd i fitxer d'entorn per a la integració amb l'Agent.
- Afegida l'ordre `configure-network-manager`, proteccions de rutes i proves automatitzades.

## Fase 9.3 — Hardening systemd

- Afegida una política declarativa de hardening per als serveis XAAC.
- Aplicats NoNewPrivileges, ProtectSystem/ProtectHome, namespaces, capabilities, dispositius, famílies d’adreces i filtres de syscalls.
- Afegits drop-ins systemd, estat auditable, CLI, documentació i proves de seguretat.

## Fase 4.7 — Multimonitor i escalat

## Fase 6.4 — Servei de primer inici

- Afegit el perfil declaratiu `config/first-boot.yaml`.
- Afegit el servei idempotent `xaac-first-boot.service`.
- Incorporada la validació inicial de model, RAM i eMMC.
- Integrada la generació o validació de la identitat persistent.
- Afegits estat auditable, marcador de finalització i registre segur de fallades.
- Afegida l'ordre `configure-first-boot` i proves automatitzades.

- Afegida política declarativa de disposició, monitor principal, resolució i escalat mixt.
- Afegits scripts Wayland (`wlr-randr`) i X11 (`xrandr`) amb reconciliació de connexió en calent.
- Preparada la integració FreeRDP amb `/multimon` i `/dynamic-resolution`.
- Afegida l’ordre `configure-display-layout` i proves automatitzades.


## Fase 4.4 — Usuari de quiosc

- Compte `xaac-kiosk` de sistema, bloquejat i amb shell no interactiva.
- Home restringit, grups mínims i variables XDG controlades.
- Configuració de tmpfiles, permisos, persistència i proves automatitzades.

## Fase 4.3 — Gestor de sessió

- Afegit `greetd` com a gestor mínim de sessió.
- Implementada la sessió dedicada `xaac-kiosk` amb autologin restringit.
- Afegits el llançador Wayland, l'entrada de sessió i la política auditable.
- Bloquejats gestors de sessió competidors i el greeter interactiu.
- Afegides proves positives, negatives, d'idempotència i de seguretat.
# Fase 4.1 — Pila gràfica mínima

### Afegit

- Perfil declaratiu `config/graphical-stack.yaml` amb Wayland principal i X11 de fallback.
- Paquets mínims per Wayland, X11, Mesa, GTK 4, libinput, xkbcommon i fonts.
- Exclusió explícita d'escriptoris complets i shells convencionals.
- Generació segura i idempotent de l'entorn gràfic de la sessió XAAC.
- Validació de backend, GTK, renderer, resolució, teclat i ratolí.
- Documentació de la fase i ampliació de la suite automatitzada.

# Fase 3.2 — Suport d’eMMC

### Afegit

- Perfil declaratiu `config/emmc.yaml` per al Dell Wyse 3040.
- Detecció segura de dispositius `mmcblkN`, capacitat, sector, tipus, CID i TRIM.
- Validació de controladors MMC/SDHCI carregats.
- Ordres `inspect-emmc` i `configure-emmc`.
- Configuració atòmica de mòduls eMMC i activació de `fstrim.timer`.
- Proteccions davant enllaços simbòlics i rutes d’activació conflictives.
- Documentació de la fase i ampliació de la suite a 333 proves.

## Fase 4.2 — Compositor

- Seleccionat labwc com a compositor Wayland mínim i Openbox com a fallback X11 controlat.
- Afegides configuracions de pantalla completa sense panells, menús, decoracions ni dreceres.
- Afegit suport declaratiu multimonitor i política de reinici segur.
- Incorporada l'ordre `configure-compositor` i proves automatitzades.

## Fase 3.1 — Inventari de maquinari Dell Wyse 3040

- Afegit el perfil declaratiu `config/hardware.yaml`.
- Afegida detecció no privilegiada mitjançant procfs, sysfs i DMI.
- Afegida comparació tipada amb resultats `pass`, `warning` i `fail`.
- Afegida l'ordre `inspect-hardware` i exportació atòmica d'informes JSON.
- Coberts CPU, RAM, eMMC, Intel/i915, Ethernet, àudio, USB, UEFI i sensors.
- Afegida documentació de la Fase 3.1 i proves automatitzades.


## Fase 2.8 — Primera imatge arrencable

### Fixed

- `build-image` ja no depén d’un `rootfs` temporal preexistent: reconstrueix automàticament el Bloc 2 en un únic workspace quan `.build/current` és incomplet o obsolet.
- Corregit l’error `Rootfs inexistent o insegur` que apareixia en invocar directament la construcció integral.

- Afegit el constructor integral d'imatges GPT arrencables en UEFI.
- Afegida l'ordre `build-image` i el mode `--dry-run`.
- Afegits assemblatge amb loop, còpia del rootfs, instal·lació GRUB, compressió gzip i hashes SHA-256.
- Afegida traçabilitat dels artefactes en el manifest i neteja segura en cas d'error.
- Suite ampliada a 292 proves amb cobertura global superior al 90%.


## Fase 2.7 — Localització i consola

- Afegida configuració declarativa de locale, fallbacks, zona horària, teclat i consola.
- Afegida l'ordre `configure-localization` amb mode `--dry-run`.
- Afegida generació segura de `locale.gen`, `default/locale`, `default/keyboard`, `console-setup`, `timezone` i `localtime`.
- Afegida traçabilitat al manifest i proves positives, negatives i d'integració CLI.

## Fase 2.5 — Esquema inicial de particions

- Afegida configuració GPT declarativa en `config/partitions.yaml`.
- Afegida l'ordre `configure-partitions`.
- Implementades particions EFI, arrel, dades persistents i recuperació.
- Afegits `gdisk`, `dosfstools`, `e2fsprogs` i `parted` al sistema base.
- Afegida generació atòmica de `/etc/fstab`.
- Afegides proteccions contra execució accidental sobre discs.
- Afegides proves positives, negatives, de seguretat i manifest.

## Fase 2.8 — Tallafoc base amb nftables

- Afegida la configuració declarativa `config/firewall.yaml`.
- Afegida l'ordre `configure-firewall` i el mode `--dry-run`.
- Incorporat `nftables` al sistema base.
- Política restrictiva `drop` per a entrada i reenviament.
- Permesos loopback, trànsit establit, DHCP i ICMP essencial.
- SSH limitat al port i a les xarxes de `config/ssh.yaml`.
- Activació segura de `nftables.service`.
- Log, manifest, documentació i proves ampliats.

## Fase 2.7 — Servidor SSH mínim i endurit

- Afegida la configuració declarativa `config/ssh.yaml`.
- Afegida l'ordre `configure-ssh` amb mode `--dry-run`.
- Incorporat `openssh-server` al sistema base.
- Desactivats root, contrasenyes, autenticació interactiva, X11, túnels i reenviaments.
- Limitat l'accés a `xaac-admin` mitjançant clau pública.
- Afegida la llista CIDR de xarxes autoritzades per a la futura política nftables.
- Integrats logs, manifest verificable, documentació i proves.

## Fase 2.6 — Xarxa mínima del sistema

- Nova configuració declarativa `config/network.yaml`.
- Nova ordre `configure-network` amb mode segur `--dry-run`.
- Configuració Ethernet determinista amb `systemd-networkd`.
- DHCPv4, resolució DNS amb `systemd-resolved` i activació de serveis sense executar systemd.
- Validacions de seguretat, escriptura atòmica, log i integració al manifest.
- Suite ampliada fins a 168 proves automatitzades.

## Fase 2.5 — Usuaris, grups i accés administratiu base

- Nova configuració declarativa `config/users.yaml`.
- Nova ordre `configure-users` amb mode segur `--dry-run`.
- Creació determinista de grups i comptes locals dins del rootfs.
- Separació entre `xaac-admin` i el compte de sistema `xaac-kiosk`.
- Comptes inicials bloquejats i absència total de contrasenyes o secrets.
- Validació estricta, log complet i integració al manifest.
- Suite ampliada fins a 160 proves automatitzades.

## Fase 2.4 — Identitat i configuració regional del sistema

- Nova configuració declarativa `config/system.yaml`.
- Nova ordre `configure-system` amb mode segur `--dry-run`.
- Configuració atòmica de hostname, hosts, locales i zona horària.
- Generació no interactiva de locales dins del rootfs.
- Validacions de seguretat, log complet i integració al manifest.
- Suite ampliada fins a 150 proves automatitzades.

## Fase 2.3 — Instal·lació del sistema base

- Nova ordre `install-packages` amb mode `--dry-run`.
- Instal·lació determinista dels paquets resolts dins del rootfs mitjançant `chroot`.
- Actualització prèvia dels índexs APT.
- Execució no interactiva i sense `Recommends` ni `Suggests`.
- Validació estricta del rootfs, noms de paquets, inclusions i exclusions.
- Log complet i integració del resultat en el manifest de construcció.
- Nova documentació i ampliació de la cobertura de proves.

## Fase 2.2 — Configuració APT del rootfs

- Repositoris APT en format Deb822 amb `Signed-By`.
- Política minimalista sense paquets recomanats ni suggerits.
- Validació del rootfs i dels keyrings declarats.
- Escriptura atòmica i protecció davant enllaços simbòlics.
- Nova ordre `configure-apt` amb mode `--dry-run`.
- Integració completa amb logs i manifest verificable.

# Changelog

Tots els canvis rellevants del projecte es documentaran en aquest fitxer.

El format segueix Keep a Changelog i el projecte utilitza versionat semàntic.

## [0.1.0] - Fase 1.4

### Afegit

- Espais de treball aïllats per construcció dins de `.build/runs`.
- Identificador únic i ordenable de construcció.
- Bloqueig atòmic contra execucions concurrents.
- Manifest temporal i punter `current` escrits de manera atòmica.
- Neteja segura i protecció contra espais de treball actius.


## [Unreleased]

### Fase 7.2 — DHCP i IP estàtica

- Afegida configuració transaccional DHCP/IPv4 estàtica per a fonts locals i remotes.
- Incorporades validació de subxarxa i DNS, snapshots, estat per a l’Agent, fallback DHCP i rollback.
- Afegida l’ordre `configure-ip-addressing` i proves automatitzades de la fase.

### Added — Fase 2.6

- Configuració declarativa del sistema base en `config/systemd.yaml`.
- Ordre `configure-systemd` amb mode segur `--dry-run`.
- Target predeterminat `multi-user.target` i consola `getty@tty1`.
- Límits de journald adaptats a l’eMMC i regles de `systemd-tmpfiles`.
- Activació, desactivació i emmascarament determinista d’unitats systemd.
- Integració amb logs, manifest verificable, documentació i proves.

### Added — Fase 2.4

- Configuració declarativa de l'arrencada UEFI en `config/uefi.yaml`.
- Ordre `configure-uefi` amb planificació `--dry-run`.
- Instal·lació de GRUB `x86_64-efi` sense modificar NVRAM.
- Fallback extraïble `EFI/BOOT/BOOTX64.EFI`, menú ocult i timeout mínim.
- Validació de kernel/initramfs, logs, manifest i proves de seguretat.

### Added

- Fase 2.1: bootstrap Debian 13 `trixie` amb `debootstrap --variant=minbase`.
- Pla immutable i auditable, mode `--dry-run`, comprovació de privilegis i logs complets.
- Rootfs aïllat per construcció, neteja de resultats parcials i integració al manifest.

### Added

- Fase 1.8: manifest complet i determinista de construcció.
- Hashes SHA-256 de configuracions, perfils, plantilles, hooks i eixides.
- Traçabilitat de paquets, repositoris i commit Git.
- Verificació posterior de la integritat del manifest.

### Added

- Fase 1.7: sistema de hooks ordenat per fases, amb permisos, timeout, entorn controlat i logs.

### Added

- Sistema segur de plantilles amb variables jeràrquiques.
- Renderització atòmica i idempotent dins de cada espai de construcció.
- Plantilles inicials per a `/etc/xaac/os-release` i `/etc/default/xaac-os`.
- Proves de variables, rutes, estructura i integració amb la CLI.

### Fase 1.5 — Resolució de paquets

- Afegida resolució determinista dels grups de paquets.
- Implementada l’herència recursiva dels perfils de maquinari.
- Afegides deduplicació, exclusions i detecció de conflictes.
- Incorporat el manifest efectiu de paquets a la CLI i a l’espai de treball.
- Ampliada la suite fins a 73 proves automatitzades.

## [0.1.0] - Fase 1.3

### Afegit

- CLI completa del constructor amb `validate`, `inspect`, `prepare`, `build` i `clean`.
- Selecció explícita de l'arrel del projecte mitjançant `--root`.
- Eixida JSON per a automatització i integració futura.
- Neteja segura limitada a `.build` i protegida amb `--force`.
- Gestió homogènia dels errors de configuració i codis d'eixida.
- Proves de totes les ordres i documentació operativa.


## [0.1.0] - Fase 1.2

### Afegit

- Models tipats i immutables de configuració del constructor.
- Càrrega segura de YAML amb errors contextualitzats.
- Configuracions inicials de build, paquets i repositoris.
- Perfils `common` i `wyse3040`.
- Validació creuada de versió, arquitectura, perfil i capacitat del disc.
- Validació de la configuració des de `scripts/build.sh`.
- Proves positives, negatives i de regressió per al model de configuració.

## [0.1.0] - Fase 1.1

### Afegit

- Estructura inicial del repositori.
- Configuració de projecte per a Python 3.13.
- Paquet Python amb estructura `src/`.
- CLI inicial `xaac-os`.
- Comprovació explícita de la versió de Python.
- Configuració de `pytest`, cobertura, Ruff i mypy.
- Documentació de preparació de `.venv` i PyCharm.
- Tests inicials de metadades, versió i compatibilitat de l'intèrpret.
- Scripts operatius de desenvolupament.
- `Makefile` amb objectius estàndard.

## Fase 2.3 - Kernel i initramfs

- Reordenació del Bloc 2 segons el calendari de desenvolupament 1.0.
- Nova configuració declarativa `config/kernel.yaml`.
- Nova ordre `configure-kernel` amb mode `--dry-run`.
- Detecció de versions instal·lades en `/lib/modules`.
- Configuració de mòduls inicials i compressió de l'initramfs.
- Creació o actualització determinista amb `update-initramfs` dins del rootfs.
- Validació de coherència entre mòduls, `vmlinuz` i `initrd.img`.
- Integració completa al manifest i log de construcció.
- Documents previs mal numerats preservats com a capacitats anticipades `EARLY_*`.
- Suite ampliada a 203 proves.

### Corregit — comprovació de dependències de la Fase 2.8

- Afegit `scripts/install-build-dependencies.sh` per instal·lar en Debian i derivats totes les eines host necessàries.
- `build-image` valida conjuntament `debootstrap`, eines loop/GPT, sistemes de fitxers, `rsync` i GRUB abans d'iniciar la construcció real.
- Els errors indiquen totes les ordres absents i una ordre APT completa, evitant fallades successives una a una.
- El mode `--dry-run` es manté sense dependències host ni accés a xarxa.

## [0.1.0] - Fase 3.3

### Afegit

- Perfil declaratiu `config/graphics.yaml` per al Dell Wyse 3040.
- Detecció de GPU PCI Intel, controlador `i915`, connectors DRM i modes de vídeo.
- Validació de doble DisplayPort, resolució mínima i arrencada sense monitor.
- Detecció de paràmetres incompatibles com `nomodeset`.
- Ordres `inspect-graphics` i `configure-graphics`.
- Configuració segura de `modules-load.d` i `modprobe.d`.
- Informes JSON atòmics i 17 proves noves.
- Suite ampliada fins a 350 proves.

## [0.1.0] - Fase 3.4

### Afegit

- Perfil declaratiu `config/ethernet.yaml` per al Dell Wyse 3040.
- Detecció de la interfície Ethernet, MAC, controlador, portadora, velocitat i dúplex.
- Selecció determinista de la millor interfície disponible.
- Diagnòstic de controladors alternatius, cable desconnectat i velocitat desconeguda.
- Suport preparat per Wake-on-LAN quan el maquinari l'exposa.
- Ordres `inspect-ethernet` i `configure-ethernet`.
- Configuració `systemd-networkd` amb DHCPv4 o IPv4 estàtica validada.
- Nomenclatura persistent, informes JSON atòmics i protecció contra enllaços simbòlics.
- 29 proves noves; suite ampliada fins a 379 proves.


## [0.1.0] - Fase 3.5

### Afegit

- Perfil declaratiu `config/audio.yaml` per al Dell Wyse 3040.
- Detecció de targetes ALSA, mòduls del kernel i disponibilitat de PipeWire.
- Identificació d'eixides HDMI/DisplayPort i analògiques, així com entrades de micròfon.
- Ordres `inspect-audio` i `configure-audio`.
- Configuració segura de `modules-load.d`, `modprobe.d` i perfil XAAC d'àudio.
- Paquets mínims ALSA, PipeWire i WirePlumber incorporats a la resolució gràfica.
- Informes JSON atòmics i protecció contra enllaços simbòlics.
- 18 proves noves; suite ampliada fins a 397 proves.


## [0.1.0] - Fase 3.6

### Afegit

- Perfil declaratiu `config/usb.yaml` per a USB i perifèrics del Dell Wyse 3040.
- Detecció de controladors USB 2.0/3.x i dispositius per VID/PID des de sysfs.
- Classificació de HID, emmagatzematge, smartcard, impressores i càmeres.
- Ordres `inspect-usb` i `configure-usb`.
- Política d'autorització amb llistes permeses i bloquejades, regles udev i informe JSON atòmic.
- Preparació declarativa de perifèrics aptes per a redirecció FreeRDP.
- Paquets mínims `usbutils`, `pcscd`, `libccid` i `cups-client`.
- Proves positives, negatives, de seguretat, idempotència i integració CLI.

## [0.1.0] - Fase 3.7

### Afegit

- Perfil `config/power.yaml` per a energia, temperatura i watchdog.
- Detecció de governors CPU, sensors tèrmics, watchdog i UEFI.
- Ordres `inspect-power` i `configure-power`.
- Desactivació declarativa de suspensió i hibernació en mode quiosc.
- Configuració del watchdog de systemd i política tèrmica XAAC.
- Documentació de la validació física de recuperació després d'una pèrdua de corrent.

## [0.1.0] - Fase 3.8

### Afegit

- Perfil `config/resources.yaml` per a l'optimització de RAM i disc del Wyse 3040.
- Detecció de memòria, swap, zram, espai lliure, opcions de muntatge i persistència de journald.
- Ordres `inspect-resources` i `configure-resources`.
- zram amb `zstd`, ajustos `sysctl`, journald volàtil limitat i `/tmp` en tmpfs.
- Política `noatime`, neteja automàtica i desactivació de serveis no essencials.
- Informes JSON atòmics, protecció contra enllaços simbòlics i conflictes systemd.
- Tancament funcional del Bloc 3 — Perfil Dell Wyse 3040.

## [0.1.0] - Fase 4.1 — Correcció tipogràfica

### Modificat

- Roboto passa a ser la família tipogràfica principal i predeterminada.
- Configuració global de Fontconfig i GTK 4 amb Noto i DejaVu com a fallback.
## Fase 4.5 — Llançament de XAAC Thin Client

- Afegit un llançador segur per a XAAC Thin Client amb Python 3.13.
- Afegides comprovacions de dependències, configuració i directori de treball.
- Evitada l'execució duplicada mitjançant `flock`.
- Integrat el llançador amb l'autostart de labwc.
- Afegides proves i documentació de la fase 4.5.


## [0.1.0] - Fase 4.6

### Afegit

- Supervisor de sessió per a XAAC Thin Client amb reinici automàtic controlat.
- Límit de reinicis, finestra temporal i backoff exponencial.
- Estat runtime atòmic i pantalla GTK 4 de degradació segura.
- Notificació best effort preparada per a XAAC Thin Client Agent.
- Integració del supervisor amb l'autostart de labwc.

## [0.1.0] - Fase 4.8

### Afegit

- Política de validació completa de la sessió gràfica XAAC.
- Comprovacions d'arrencada, Wayland, labwc i execució del client.
- Límits de temps d'arrencada, memòria i CPU en repòs.
- Validació d'estabilitat de systemd i absència d'escriptoris o terminals convencionals.
- Ordre `validate-graphical-session`, servei systemd i informe runtime.
- Tancament funcional del Bloc 4 — Sessió gràfica.


## [0.1.0] - Fase 5.1

### Afegit

- Model d’amenaces formal per al mode quiosc.
- Política declarativa amb denegació per defecte per a accions, dreceres, processos, dispositius i sessions.
- Generació separada de la política efectiva i la documentació del model d’amenaces.
- Ordre `configure-kiosk-restrictions` amb mode `--dry-run`.
- Validació estricta, escriptura atòmica, idempotència i protecció contra enllaços simbòlics.

## [0.1.0] - Fase 5.2

### Afegit

- Política declarativa `shortcut-lockdown.yaml` amb denegació per defecte.
- Bloqueig del canvi d’aplicació, tancament de finestres, menús, execució ràpida, captures i dreceres de sistema.
- Configuracions efectives per a Wayland/labwc i X11/Openbox sense dreceres predeterminades.
- Ordre `configure-shortcut-lockdown` amb mode `--dry-run`.
- Política JSON auditable, escriptura atòmica, idempotència i protecció contra enllaços simbòlics.

## [0.1.0] - Fase 5.3

### Afegit

- Política declarativa `terminal-lockdown.yaml` amb denegació per defecte.
- Exclusió explícita dels emuladors de terminal comuns de la selecció de paquets.
- Bloqueig d’intèrprets, ordres arbitràries i fitxers `.desktop` creats per l’usuari.
- Restricció dels esquemes URI i desactivació dels obridors genèrics.
- `PATH` mínim, absolut i limitat als executables interns de XAAC.
- Ordre `configure-terminal-lockdown` amb mode `--dry-run`.
- Política JSON auditable, escriptura atòmica, idempotència i protecció contra enllaços simbòlics.

## [0.1.0] - Fase 5.4

### Afegit

- Política declarativa `tty-control.yaml` amb denegació per defecte.
- Deshabilitació de `getty` i `autovt` als TTY 1–11.
- Reserva de `tty12` com a únic TTY administratiu local.
- Accés restringit a `xaac-admin` amb autenticació obligatòria.
- Configuració de `systemd-logind` sense terminals virtuals automàtics.
- Bloqueig del canvi de TTY per a la sessió de quiosc i reserva coherent de `Ctrl+Alt+F12`.
- Ordre `configure-tty-control` amb mode `--dry-run`.
- Política JSON auditable, escriptura atòmica, idempotència i protecció contra enllaços simbòlics.

## [0.1.0] - Fase 5.5

### Afegit

- Política declarativa `kiosk-filesystem.yaml` amb denegació per defecte.
- `home` efímer sobre `tmpfs`, amb límits de mida i inodes i opcions `nosuid,nodev,noexec`.
- Directoris permesos, descàrregues restringides i `umask 0077`.
- Neteja idempotent de l'estat del quiosc a l'inici i al final de la sessió.
- Configuració `tmpfiles.d`, servei systemd, entorn i política JSON auditable.
- Ordre `configure-kiosk-filesystem` amb mode `--dry-run`.

## [0.1.0] - Fase 5.6

### Afegit

- Política declarativa `local-device-control.yaml` amb denegació per defecte.
- Control USB per classes i llistes VID/PID.
- Bloqueig de l'emmagatzematge massiu, l'automuntatge i les accions UDisks2 del quiosc.
- Política explícita per a càmeres, smartcards i impressores.
- Ordre `configure-local-device-control` amb mode `--dry-run`.
- Regles udev, política polkit i manifest JSON auditable.

## [0.1.0] - Fase 5.7

### Afegit

- Política declarativa `power-action-control.yaml` amb denegació per defecte.
- Apagada i reinici canalitzats exclusivament a través de XAAC Agent i amb confirmació.
- Bloqueig de suspensió, hibernació i accions directes de `systemd-logind` per a `xaac-kiosk`.
- Inhibició de tecles físiques d’energia i protecció contra peticions accidentals o duplicades.
- Política de recuperació que prioritza el reinici de la sessió davant una fallada del client.
- Ordre `configure-power-action-control` amb mode `--dry-run`.
- Configuració logind, política Polkit, helper restringit i manifest JSON auditable.

## [0.1.0] - Fase 6.1

### Afegit

- Perfil declaratiu per al paquet Debian de XAAC Thin Client.
- Validació amb `dpkg-deb` de nom, versió, arquitectura i dependències.
- Verificació SHA-256, política anti-downgrade i compatibilitat de revisions patch.
- Instal·lació atòmica dins del rootfs, configuració auditable i preferència APT estable.
- Ordre `install-xaac-thin-client` amb mode `--dry-run`.
- Proves positives, negatives, de seguretat i d’instal·lació.

## [0.1.0] - Fase 6.2

### Afegit

- Perfil declaratiu del paquet Debian XAAC Thin Client Agent.
- Validació de nom, versió, arquitectura, dependències i SHA-256.
- Usuari i grup de sistema `xaac-agent` amb shell no interactiva.
- Directoris persistents d'estat i logs amb permisos restrictius.
- Configuració inicial gestionada i manifest auditable.
- Servei systemd habilitat amb reinici controlat i hardening inicial.
- Ordre `install-xaac-agent` amb mode `--dry-run`.

## [0.1.0] - Fase 6.3

### Afegit

- Perfil declaratiu de la identitat persistent del dispositiu.
- UUID v4, número de sèrie DMI, MAC unicast i hostname estable.
- Certificat X.509 inicial RSA-3072 i clau privada protegida.
- Persistència idempotent per a XAAC Agent i preparació de l'enrolament XMS.
- Inicialització coherent de `/etc/hostname` i `/etc/machine-id`.
- Ordre `configure-device-identity` amb mode `--dry-run`.
- Validacions de rutes, permisos, symlinks i material criptogràfic.

## [0.1.0] - Fase 6.5

### Afegit

- Canal IPC local Client-Agent basat en socket Unix privat.
- Protocol JSON versionat `xaac-local-ipc` v1 amb esquema estricte i límit de 64 KiB.
- Autenticació local obligatòria amb credencials del peer (`SO_PEERCRED`).
- Llista tancada de tipus de missatge i rebuig de missatges desconeguts.
- Configuració, manifest auditable i regla `systemd-tmpfiles` per a `/run/xaac`.
- Ordre `configure-ipc` amb mode `--dry-run`.

## [0.1.0] - Fase 6.6

### Afegit

- Perfil declaratiu per a l'aplicació transaccional de polítiques XAAC.
- Format `xaac-device-policy` v1 amb esquema estricte, límit de mida i digest SHA-256 obligatori.
- Recepció i validació amb llista tancada de seccions autoritzades.
- Àrea de staging persistent i escriptures JSON atòmiques.
- Aplicació amb còpia de la política anterior, confirmació explícita i estat auditable.
- Rollback automàtic i restauració de l'última revisió vàlida.
- Ordre `configure-policy-application` amb mode `--dry-run`.

## Fase 6.7 — Inventari

- Afegit el perfil declaratiu `config/device-inventory.yaml`.
- Incorporada la recollida de maquinari, sistema, paquets i perifèrics USB.
- Afegida la detecció de versions dels components XAAC i de l'estat local.
- Afegits informe i estat atòmics amb digest SHA-256 i manifest versionat.
- Afegida l'ordre `collect-device-inventory` i proves automatitzades.

## Fase 6.8 — Enrolament XMS

- Afegit el perfil declaratiu `config/xms-enrollment.yaml`.
- Afegit el gestor local d’enrolament XMS amb token, aprovació i certificat.
- Afegits els fluxos de renovació, desenrolament i error segur.
- Afegida l’ordre `configure-xms-enrollment` i el mode `--dry-run`.
- Afegides proves positives, negatives, de permisos i de transicions d’estat.
- Tancat el Bloc 6 — Integració XAAC.

## [0.1.0] - Fase 7.3

### Afegit

- Configuració declarativa de DNS amb `systemd-resolved`.
- Dominis de cerca, DNSSEC i DNS-over-TLS oportunista.
- Configuració NTP amb `systemd-timesyncd` i servidors de fallback.
- Proxy HTTP/HTTPS global i integració amb APT.
- Excepcions de proxy, diagnòstic versionat i estat per a XAAC Agent.
- Aplicació local o remota, snapshot i rollback.
- Ordre `configure-network-services` amb mode `--dry-run`.

## [0.1.0] - Fase 7.5

### Afegit

- Autenticació IEEE 802.1X cablejada amb `wpa_supplicant`.
- EAP-TLS i PEAP/MSCHAPv2 amb validació estricta.
- Gestió protegida de certificats, claus i credencials.
- Estat, diagnòstic i renovació integrats amb XAAC Agent.
- Aplicació local o remota, snapshot i rollback transaccional.
- Ordre `configure-ieee8021x` amb mode `--dry-run`.
## [0.1.0] - Fase 7.7

### Afegit

- OpenSSH restringit a l’usuari administratiu i a xarxes corporatives autoritzades.
- Autenticació exclusiva amb claus públiques aprovades i algoritmes moderns.
- Servei desactivat de manera predeterminada i activació temporal amb caducitat automàtica.
- Helper administratiu `xaac-ssh-access` amb duració limitada per política.
- Estat versionat per a XAAC Agent, registres en journald i regles d’auditoria.
- Escriptures atòmiques, permisos restrictius i protecció contra enllaços simbòlics.
- Ampliació de `configure-ssh` i proves automatitzades de seguretat i idempotència.


## [0.1.0] - Fase 7.8

### Afegit

- Tallafoc persistent basat en `nftables` amb polítiques `input` i `forward` per defecte a `drop`.
- Xarxes de gestió IPv4 i IPv6 declaratives i validades estrictament.
- Regles diferenciades per a OpenSSH, XAAC Agent i RustDesk.
- Serveis Agent i RustDesk tancats per defecte fins que una política declare ports autoritzats.
- Conservació del trànsit de loopback, connexions establides, DHCP i ICMP essencial.
- Estat JSON versionat per a XAAC Agent en `/var/lib/xaac-agent/network/firewall.json`.
- Persistència mitjançant `nftables.service`, escriptures atòmiques i protecció contra enllaços simbòlics.
- Validació de xarxes, ports, esquema, rutes d’estat i idempotència.
- Tancat el Bloc 7 — Xarxa i administració.

## [0.1.0] - Fase 8.4

### Afegit

- Servei `rustdesk-xaac.service` executat amb l'usuari dedicat `xaac-rustdesk`.
- Dependència de `network-online.target` i comprovació de binari i configuració gestionada.
- Política de reinici controlada, límits d'arrencada i temps de parada.
- Sandboxing systemd amb privilegis mínims i sense capabilities.
- Declaracions `systemd-sysusers` i `systemd-tmpfiles` per a usuari i directoris d'estat.
- Estat JSON per a XAAC Agent, desactivat per defecte i preparat per a activació sota demanda.
- Ordre `configure-rustdesk-service` amb mode `--dry-run`.

## [0.1.0] - Fase 8.5

### Afegit

- Activació sota demanda de `rustdesk-xaac.service` des d'una ordre local o una petició XMS.
- Duració limitada per política, caducitat UTC i tancament automàtic mitjançant systemd.
- Tokens d'un sol ús amb longitud mínima i persistència exclusiva del hash SHA-256.
- Petició efímera amb permisos `0600` i estat versionat per a XAAC Agent.
- Ordres `configure-rustdesk-activation`, `activate-rustdesk-support` i `deactivate-rustdesk-support` amb `--dry-run`.

## [0.1.0] - Fase 8.6

### Afegit

- Política de consentiment obligatori per defecte per a sessions de XAAC Remote Support.
- Mode sense consentiment restringit a XMS, dispositius gestionats i autorització explícita de política.
- Notificació de quiosc amb operador, motiu i caducitat de la sessió.
- Decisions d'aprovació, denegació i cancel·lació per part de l'usuari.
- Estat versionat, peticions efímeres i registre JSON Lines de peticions i decisions.
- Ordres `configure-rustdesk-consent`, `request-rustdesk-consent` i `decide-rustdesk-consent` amb `--dry-run`.

## [0.1.0] - Fase 8.7

### Afegit

- Auditoria append-only de sessions de XAAC Remote Support en format JSON Lines.
- Registre d'inici i final, operador, dispositiu, motiu, origen, duració i estat final.
- Sessió activa efímera amb permisos `0600` i estat versionat per a XAAC Agent.
- Validació UTC, exclusió de sessions simultànies i protecció contra symlinks.
- Ordres `configure-rustdesk-audit`, `start-rustdesk-audit` i `end-rustdesk-audit` amb `--dry-run`.

## [0.1.0] - Fase 9.4

### Afegit

- Perfils AppArmor declaratius per a XAAC Agent, XAAC Thin Client i XAAC Remote Support.
- Modes `enforce` i `complain` gestionats mitjançant `force-complain`.
- Regles de mínim privilegi per a fitxers, xarxa, capabilities i senyals.
- Auditoria de denegacions i estat versionat per a XAAC Agent.
- Paquets `apparmor` i `apparmor-utils` incorporats a la imatge base.
- Ordre `configure-apparmor` amb mode `--dry-run`.
- Validació de rutes, tokens, duplicats, idempotència i enllaços simbòlics.

## Fase 9.5 — Hardening del kernel

- Política declarativa `config/kernel-hardening.yaml`.
- ASLR complet i restricció de `ptrace`, informació del kernel, BPF i comptadors de rendiment.
- Desactivació de core dumps i Magic SysRq.
- Enduriment IPv4/IPv6 contra redirects, source routing i forwarding no autoritzat.
- Política de bloqueig de sistemes de fitxers i protocols de xarxa no necessaris.
- Ordre `configure-kernel-hardening` amb mode `--dry-run`.
- Estat auditable per a XAAC Agent, escriptura atòmica i protecció contra symlinks.

## [0.1.0] - Fase 9.6

### Afegit

- Política declarativa d'integritat de fitxers amb hashes SHA-256.
- Baseline protegida per a fitxers crítics de XAAC, systemd, AppArmor i kernel.
- Verificació periòdica mitjançant servei i temporitzador systemd.
- Detecció de modificacions, eliminacions i substitucions no autoritzades.
- Estat d'alerta versionat per a XAAC Agent i registre preparat per a auditoria.
- Reparació opcional des d'una còpia baseline local controlada.
- Excepcions declaratives per a fitxers temporals, bloquejos i logs.
- Ordres `configure-file-integrity` i `verify-file-integrity --repair`.

## [0.1.0] - Fase 9.7

### Afegit

- Política declarativa de confiança per al repositori APT XAAC.
- Ús obligatori de `Signed-By`, HTTPS i verificació de vigència de metadades.
- Model de clau activa, claus anteriors confiables i empremtes revocades.
- Bloqueig de repositoris insegurs, degradacions i paquets no autenticats.
- Verificador offline amb `gpgv`, manifest signat i hashes SHA-256.
- Estat auditable per a XAAC Agent i ordre `configure-package-signing`.

## Fase 9.8 — Secure Boot i TPM

- Afegida política declarativa de viabilitat per al Dell Wyse 3040.
- Decidida una cadena d’arrencada Debian signada amb activació condicional de Secure Boot.
- TPM 2.0 queda com a capacitat opcional i mai com a dependència d’arrencada o recuperació.
- Afegits probe local, estat auditable per a XAAC Agent i ADR-0009.
- Afegida l’ordre `configure-secure-boot-tpm` i proves positives, negatives, d’idempotència i permisos.
- Tancat el Bloc 9 — Seguretat.

## [0.1.0] - Fase 10.1

### Afegit

- Model declaratiu d’actualitzacions amb components, canals i finestres de manteniment.
- Política SemVer amb prereleases controlades, versió mínima i bloqueig de downgrades.
- Validació de dependències i conjunts atòmics de components.
- Màquina d’estats completa per a comprovació, descàrrega, staging, instal·lació, validació i rollback.
- Estat inicial auditable per a XAAC Agent i política efectiva en format JSON.
- Ordre `configure-update-model` amb mode `--dry-run`.
- Proves positives, negatives, d’idempotència, permisos, CLI i protecció contra symlinks.
- Iniciat el Bloc 10 — Actualitzacions.

## [0.1.0] - Fase 10.2

### Afegit

- Política declarativa de repositori APT XAAC amb canals de laboratori, pilot i producció.
- Estructura determinista `pool/` i `dists/` per component, suite i arquitectura.
- Generació obligatòria de `Packages`, `Release`, `InRelease` i `Release.gpg`.
- Signatura obligatòria, SHA-256/SHA-512 i vigència limitada de metadades.
- Configuració de publicació, retenció de versions i snapshots.
- Model de mirall local amb verificació obligatòria de signatures.
- Ordre `configure-xaac-apt-repository` amb mode `--dry-run`.
- Estat auditable per a XAAC Agent, escriptures atòmiques i protecció contra symlinks.

## [0.1.0] - Fase 10.3

### Afegit

- Servei declaratiu de comprovació, descàrrega i staging d’actualitzacions.
- Temporitzador systemd persistent amb interval i jitter configurables.
- Control preventiu d’espai lliure, mida màxima de descàrrega, timeout i reintents.
- Bloqueig exclusiu d’execució, descàrregues parcials i escriptura sincronitzada.
- Estat persistent i auditable amb màquina d’estats segura.
- Unitat systemd endurida i regles tmpfiles per als directoris de treball.
- Ordre `configure-update-service` amb mode `--dry-run`.
- Proves positives, negatives, d’idempotència, permisos, CLI i symlinks.

## [0.1.0] - Fase 10.5

### Afegit

- Política declarativa d’instal·lació transaccional d’actualitzacions verificades.
- Punt de recuperació obligatori amb estat de paquets i configuració.
- Instal·lació no interactiva amb bloqueig, conjunts atòmics i staging verificat.
- Reinici restringit als serveis autoritzats que hagen canviat.
- Validació posterior fail-closed de paquets, serveis, sessió del client i salut de l’Agent.
- Confirmació explícita, conservació d’evidències i rollback automàtic davant fallades.
- Servei systemd endurit, estat auditable i ordre `configure-transactional-update`.

## [0.1.0] - Fase 10.6

### Afegit

- Política declarativa de rollback per a transaccions d'actualització fallides.
- Restauració obligatòria de versions anteriors, configuració i estat transaccional.
- Reinici restringit als serveis afectats i autoritzats.
- Validació posterior fail-closed de paquets, configuració, serveis, client i Agent.
- Registre persistent i bloqueig de versions defectuoses amb motiu i transacció.
- Conservació d'evidències, servei systemd endurit i ordre `configure-package-rollback`.

## [0.1.0] - Fase 11.1

### Afegit

- Model declaratiu d'estats de recuperació per a fallades d'aplicació, sessió, actualització i integritat.
- Comptadors amb finestres temporals i llindars estrictament creixents.
- Estats `healthy`, `degraded`, `recovering`, `safe` i `manual_intervention` amb classificació determinista.
- Accions i notificacions obligatòries a XAAC Agent i XMS segons la severitat.
- Política *fail-closed*, conservació d'evidències i prohibició del `factory reset` automàtic.
- Estat persistent amb permisos restrictius, escriptures atòmiques i protecció contra symlinks.
- Ordre `configure-recovery-model`, documentació i proves positives, negatives i d'idempotència.
