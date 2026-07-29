# Fase 3.2 — Suport d’eMMC

## Objectiu

Garantir que el constructor identifica l’eMMC del Dell Wyse 3040, comprova que és apta per a la instal·lació i prepara el sistema arrel per arrancar i treballar amb aquest dispositiu de forma previsible.

## Implementació

La fase incorpora `config/emmc.yaml` i el mòdul `emmc_support.py`.

La detecció consulta `sysfs` i `/proc/modules` sense requerir privilegis i obté:

- dispositius `mmcblkN`, excloent-ne les particions;
- capacitat efectiva;
- caràcter extraïble o fix;
- naturalesa rotacional o no rotacional;
- mida lògica de sector;
- capacitat de descarte/TRIM;
- tipus MMC i CID quan el kernel els publica;
- mòduls del kernel carregats.

La comparació amb el perfil valida la capacitat mínima, el tipus de dispositiu, el sector lògic, la disponibilitat de TRIM i almenys un controlador MMC/SDHCI admès.

## Configuració del rootfs

`configure-emmc` genera de manera atòmica:

- `/etc/modules-load.d/xaac-emmc.conf`;
- `/etc/xaac/emmc.conf`;
- l’activació de `fstrim.timer` en `timers.target.wants`.

Els muntatges continuen basats en etiquetes GPT/filesystem (`XAAC_ROOT`, `XAAC_DATA` i `XAAC_RECOVERY`) i mantenen `noatime`. No s’activa `discard` continu: s’utilitza TRIM periòdic mitjançant systemd.

## Ordres

```bash
xaac-os --root . inspect-emmc
xaac-os --root . --json inspect-emmc
xaac-os --root . inspect-emmc --report reports/emmc.json
xaac-os --root . configure-emmc --dry-run
xaac-os --root . configure-emmc
```

La configuració real requereix un espai de treball existent i que el rootfs continga la unitat `fstrim.timer`, normalment proporcionada per `util-linux`.

## Seguretat i idempotència

- no s’escriu sobre enllaços simbòlics inesperats;
- no es substitueixen rutes d’activació que no siguen enllaços;
- un enllaç existent només s’accepta si apunta a la unitat correcta;
- el mode `--dry-run` no modifica el rootfs;
- la detecció tracta fitxers absents o valors invàlids com a dades desconegudes, sense excepcions no controlades.

## Proves

S’han afegit proves positives, negatives, casos límit, detecció incompleta, selecció entre múltiples eMMC, TRIM, mòduls, escriptura atòmica, activació systemd, conflictes de rutes i CLI.
