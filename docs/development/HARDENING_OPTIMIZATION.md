# Bloc 9 — Hardening i optimització final

**Estat:** EN VALIDACIÓ FINAL — Fases 9.1–9.4 implementades; pendent executar la ISO candidata en maquinari real.

Aquest és el bloc final de consolidació tècnica abans de les proves finals de
release. No substitueix el `docs/phases/block-09/` històric del calendari original:
aquell directori documenta la primera implementació de seguretat; aquest bloc
revisa el que acaba realment dins de la ISO de producció actual.

## Objectiu

La ISO final ha d'aplicar de manera efectiva les polítiques de seguretat que el
projecte declara, reduir serveis i escriptures innecessàries i mantindre's dins
les restriccions del Dell Wyse 3040 (2 GB de RAM i 8 GB d'eMMC), sense degradar
XAAC Thin Client, XAAC Thin Client VPN ni XAAC Thin Client Agent.

Per reduir el cost de les iteracions, les fases 9.1–9.3 es validen amb tests i
gates estàtics. No es preveu generar una ISO completa en cada fase. La generació
de la ISO queda concentrada en la fase 9.4, quan el bloc estiga consolidat.

## Fase 9.1 — Línia base efectiva de xarxa

La revisió inicial ha detectat una diferència entre configuració declarativa i
constructor de producció: `config/ssh.yaml` estableix SSH deshabilitat per defecte,
però el constructor habilitava `ssh.service` incondicionalment. Igualment,
`config/firewall.yaml` existia però la fase de producció només habilitava el servei
nftables sense garantir que el ruleset XAAC haguera sigut instal·lat.

La Fase 9.1 corregeix aquesta divergència:

- el constructor de producció aplica `config/ssh.yaml` mitjançant el configurador
  canònic de XAAC;
- SSH queda deshabilitat a l'arrencada i només pot activar-se temporalment amb
  `/usr/local/sbin/xaac-ssh-access`, mantenint autenticació exclusiva per clau;
- el constructor aplica `config/firewall.yaml` i deixa nftables habilitat amb
  política `drop` per a entrada i forwarding;
- abans de continuar, el chroot valida `sshd -t`, `nft -c -f /etc/nftables.conf`,
  la desactivació de `ssh.service` i l'activació de `nftables.service`;
- els configuradors SSH/nftables accepten ara també el rootfs segur del constructor
  `.build/production/rootfs`, sense relaxar la protecció contra `/` o `/rootfs`.

Aquesta fase no genera ISO.

## Fase 9.2 — Kernel, memòria, eMMC i serveis mínims

Fase 9.2 implementada. La configuració declarativa deixa de ser només històrica i
passa a formar part del constructor ISO de producció.

Canvis consolidats:

- `squashfs` s'ha retirat explícitament de la blacklist del kernel i es declara
  com a mòdul permés en runtime, perquè és imprescindible per al Live i per al
  desplegament de `filesystem.squashfs` durant la instal·lació;
- el constructor aplica `config/kernel-hardening.yaml` al rootfs abans de generar
  l'initramfs, incloent ASLR, restricció de `ptrace`, desactivació de core dumps,
  SysRq i mòduls/protocols no utilitzats;
- el build **no executa `sysctl` contra el chroot**, perquè això afectaria el kernel
  de la màquina constructora; només instal·la i valida estàticament la política,
  que entra en vigor quan arranca el terminal;
- `config/resources.yaml` passa a ser efectiva: zram del 50 % de RAM amb `zstd`,
  `vm.swappiness=100`, `vm.page-cluster=0`, journald volàtil limitat a 32 MiB i
  `/tmp` sobre tmpfs limitat a 128 MiB;
- s'activa `fstrim.timer` i el sistema instal·lat conserva `noatime` en les
  particions ext4 de root, dades i recuperació;
- es bloquegen `apt-daily`, `apt-daily-upgrade` i els seus timers, així com
  `man-db.timer`, per evitar treball periòdic i escriptures a eMMC fora del model
  d'actualització XAAC;
- abans del SquashFS es netegen la cache d'APT, les llistes descarregades i els
  `.deb` temporals copiats només per a construir la imatge;
- s'ha corregit la regressió residual de la Fase 9.1: l'instal·lador genera claus
  host SSH úniques i valida `sshd`, però deixa `ssh.service` deshabilitat.

No es genera ISO en aquesta fase. La comprovació efectiva de zram, TRIM, ús de RAM
i comportament de journald es reserva per al maquinari real en la Fase 9.4.

## Fase 9.3 — Hardening de serveis i AppArmor real

Fase 9.3 implementada sobre els artefactes que arriben realment a la ISO de
producció. La política històrica no s'ha aplicat a cegues: els noms antics
`xaac-thin-client.service`, `xaac-session-supervisor.service` i `/usr/sbin/xaac-agent`
no formen part del runtime actual i, per tant, no reben drop-ins ni perfils ficticis.

Canvis consolidats:

- `xaac-agent.service` i `xaac-privileged-helper.service` conserven el hardening
  propietat del `.deb` de XAAC Agent. El constructor el valida explícitament i
  comprova que l'Agent continue amb `CapabilityBoundingSet=` buit, que no es
  reintroduïsca `CAP_NET_ADMIN` i que el helper només expose `CAP_SYS_BOOT`;
- `config/systemd-hardening.yaml` passa a descriure només el servei del sistema
  que necessita una capa addicional de l'OS en aquesta versió:
  `xaac-vpn-manager.service`. El drop-in aplica `ProtectSystem=strict`,
  `NoNewPrivileges`, `MemoryDenyWriteExecute`, `RestrictNamespaces`,
  `DevicePolicy=closed`, filtres de syscalls i un `CapabilityBoundingSet` buit;
- el build executa `systemd-analyze verify` sobre Agent, helper i VPN manager, de
  manera que una unitat o drop-in incoherent impedeix continuar;
- AppArmor queda habilitat explícitament en la imatge i els perfils XAAC apunten
  als executables reals `/usr/bin/xaac-agent`, `/usr/bin/xaac-thinclient` i
  `/usr/bin/xaac-thin-client-vpn`;
- els tres perfils personalitzats entren inicialment en **mode `complain`**. Són
  processos Python/GTK amb accés a D-Bus, Wayland, FreeRDP i diversos recursos
  dinàmics; imposar `enforce` sense observar el maquinari real podria bloquejar
  el quiosc o la VPN. Aquesta decisió és deliberada i forma part del gate 9.4;
- durant la construcció els perfils es compilen amb `apparmor_parser -Q -K`, que
  valida sintaxi i includes però no carrega cap política al kernel de la màquina
  constructora;

No es genera ISO en aquesta fase. En la Fase 9.4, la validació física ha de revisar
`aa-status` i els `DENIED`/audits d'AppArmor durant l'ús real de Thin Client, VPN
i Agent abans de considerar qualsevol promoció selectiva de `complain` a
`enforce`.

## Fase 9.4 — Consolidació, ISO única i validació física

Fase 9.4 implementada. El codi queda congelat com a candidat per a una única
construcció neta i una validació física reproduïble. El tancament del Bloc 9 es
produeix només quan el terminal real supera el gate i les comprovacions manuals
funcionals.

### Gate previ a la ISO

`scripts/validate-block9-release.sh` és el punt únic de validació abans del build.
Executa, en aquest ordre:

- gate canònic i d'integració del Bloc 7;
- gate visual del Bloc 8;
- gate de hardening del Bloc 9;
- suite completa de `pytest`;
- validació amb `dpkg-deb` dels tres paquets que el constructor de producció
  integra actualment: Agent, Thin Client VPN i Thin Client.

El `build-production-iso.sh` executa automàticament aquest gate abans d'elevar
privilegis. També es pot executar explícitament:

```sh
./scripts/validate-block9-release.sh
```

Després del gate, la candidata es construeix una sola vegada:

```sh
./scripts/build-production-iso.sh --clean
```

La fase `verify` genera al costat de la ISO:

- `xaac-thin-client-os-amd64.iso.sha256`;
- `xaac-thin-client-os-amd64.iso.release.json`.

El manifest de release registra versió, perfil, arquitectura, mida i SHA-256 de
la ISO i del SquashFS. També deixa explícit que AppArmor continua en `complain`
fins revisar els accessos reals.

### Gate en el Dell Wyse 3040 instal·lat

La candidata instal·la `/usr/local/sbin/xaac-block9-validate` com `root:root 0750`.
És un validador de només lectura: no activa serveis, no modifica `sysctl` i no
carrega ni promou perfils AppArmor. S'executa així:

```sh
sudo /usr/local/sbin/xaac-block9-validate
```

Per defecte genera:

- `/var/log/xaac/block9-validation.txt`;
- `/var/log/xaac/block9-validation-evidence/`.

El gate comprova, entre altres punts:

- Dell Wyse 3040, UEFI i arrel `XAAC_ROOT`;
- mínim de RAM, ús en repòs, espai lliure i `noatime`;
- zram 50 %, `zstd`, swap activa i `swappiness=100`;
- `/tmp` en tmpfs, journald volàtil i `fstrim.timer`;
- timers APT emmascarats;
- sysctls de hardening i SquashFS no bloquejat;
- SSH deshabilitat, nftables actiu amb política d'entrada `drop`;
- NetworkManager, greetd, VPN manager, AppArmor i socket privilegiat;
- paquets XAAC i procés del Thin Client;
- absència d'unitats systemd fallides;
- temps d'arrencada objectiu de 45 segons.

Els events AppArmor `DENIED` es marquen com **REVIEW**, no com a fallada automàtica,
perquè els perfils estan deliberadament en `complain`. L'evidència s'ha de revisar
abans de plantejar qualsevol promoció a `enforce`.

### Validació funcional manual

Després d'un gate automàtic sense `FAIL`, cal verificar en el terminal real:

1. arrencada, pantalla de quiosc i XAAC Thin Client;
2. connexió RDP completa;
3. VPN opcional i, quan estiga configurada, autenticació 2FA i connexió;
4. enrolament/operació de XAAC Thin Client Agent quan corresponga;
5. accés administratiu local i activació temporal d'SSH;
6. reinici i apagada amb l'experiència visual prevista.


Només després de la validació física i funcional es pot marcar el Bloc 9 com a
tancat.
