# Bloc 9 — Hardening i optimització final

**Estat:** EN CURS — Fase 9.1 implementada, pendent de validació de les fases següents.

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

Pendent. Inclourà la reconciliació de `kernel-hardening.yaml` i `resources.yaml`
amb el camí de producció, revisant especialment els mòduls imprescindibles per a
Live/instal·lació, zram, journald volàtil, escriptures a eMMC, temporitzadors i
serveis prescindibles.

No es generarà ISO en aquesta fase mentre els gates estàtics siguen satisfactoris.

## Fase 9.3 — Hardening de serveis i AppArmor real

Pendent. Revisarà els noms i executables efectius de les unitats i paquets actuals
abans d'aplicar qualsevol drop-in systemd o perfil AppArmor. La regla és no
aplicar una política històrica si pot ampliar privilegis o apuntar a un executable
que ja no existeix.

També es farà una verificació de regressió dels contractes Agent, VPN, quiosc i
experiència d'appliance.

## Fase 9.4 — Consolidació, ISO única i validació física

Pendent. Serà el gate final del bloc:

- suite completa de tests;
- validators dels Blocs 7, 8 i 9;
- construcció neta amb `./scripts/build-production-iso.sh --clean`;
- verificació de l'artefacte i instal·lació en Dell Wyse 3040;
- mesures de RAM, zram, espai lliure, temps d'arrencada, serveis actius i política
  efectiva de xarxa;
- prova funcional de XAAC Thin Client, VPN, Agent, administració local, reinici i
  apagada.

Només després d'aquesta validació es marcarà el Bloc 9 com a tancat.
