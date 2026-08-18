# Fase 10.4 — Recuperació

## Objectiu

La Fase 10.4 incorpora un camí de recuperació local que continua disponible quan la sessió gràfica, la VPN o els components XAAC no poden arrancar. No implementa una segona arrel A/B i reutilitza els punts de recuperació transaccionals creats en la Fase 10.2.

## CLI administrativa

La interfície canònica és:

```bash
sudo xaac-recovery status
sudo xaac-recovery rollback --yes
sudo xaac-recovery repair --yes
sudo xaac-recovery repair --restore-configuration --yes
sudo xaac-recovery network-on --yes
sudo xaac-recovery network-off --yes
```

`rollback` restaura paquets i configuració de l'últim punt segur mitjançant el mateix runtime verificat de la Fase 10.2. `repair --restore-configuration` permet recuperar només la configuració anterior sense canviar versions de paquets.

`repair` està bloquejat fora del mode de recuperació i executa, en aquest ordre, `dpkg --configure -a`, `dpkg --audit`, regeneració d'initramfs i `update-grub`. Després comprova que `grub.cfg` conserve tant l'entrada normal com la de recovery.

## Recovery des de GRUB

La imatge instal·la una entrada addicional:

```text
XAAC Thin Client OS — Recovery
```

L'arranc normal continua ocultant el menú. El timeout ocult passa a un segon per permetre que un administrador prema `Esc` immediatament després del firmware i mostre GRUB sense deixar una pantalla de menú permanent.

L'entrada de recovery arranca amb:

```text
systemd.unit=xaac-recovery.target
```

El target:

- no depèn de `graphical.target`;
- entra en conflicte amb `greetd`, XAAC Thin Client VPN i XAAC Agent;
- no activa NetworkManager per defecte;
- proporciona `getty@tty1` per autenticar `xaac-admin` amb la política PAM normal;
- no habilita cap shell root ni cap bypass d'autenticació.

Després d'iniciar sessió, l'administrador pot executar:

```bash
sudo xaac-recovery menu
```

## Xarxa en recovery

La xarxa està desactivada per defecte. Només s'activa explícitament amb `network-on --yes` i es pot tornar a aturar amb `network-off --yes`. Això evita que un terminal en estat degradat expose serveis de xarxa innecessaris durant una reparació local.

## Evidència i estat

Les accions de recovery escriuen estat root-only a:

```text
/var/lib/xaac-recovery/state.json
```

i auditoria persistent a:

```text
/var/log/xaac-recovery/recovery.jsonl
```

No s'hi registren contrasenyes, tokens, claus ni contingut dels backups.

## Factory reset

El factory reset **no s'habilita en aquesta fase**. El repositori conserva prototips d'un full de ruta anterior, però no formen part del constructor de producció.

La raó és deliberada: un factory reset segur necessita una imatge base independent, versionada i signada que puga restaurar-se des de la partició `XAAC_RECOVERY`. La ISO actual encara no provisiona aquest artefacte. Exposar una ordre que simplement esborre dades o copie una arrel no autenticada seria pitjor que no oferir-la.

Per tant, la política 10.4 és *fail-closed*:

- cap factory reset automàtic;
- cap factory reset remot no atès;
- cap esborrat massiu de configuració;
- la futura operació només podrà activar-se quan la Fase 10.5 valide un artefacte factory signat i el seu procés de restauració física.

## Validació

La fase es valida sense generar ISO mitjançant:

```bash
./scripts/validate-block10-phase4.sh
```

La selecció real de l'entrada GRUB i el comportament físic del Wyse 3040 queden al gate de la Fase 10.5, on ja estava prevista la construcció final de la ISO.
