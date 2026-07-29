# Fase 3.1 — Inventari de maquinari Dell Wyse 3040

## Objectiu

Definir formalment el perfil físic del Dell Wyse 3040 i proporcionar una detecció local,
no privilegiada i auditable que permeta comparar el dispositiu real amb el perfil esperat.

## Configuració

El perfil es troba en `config/hardware.yaml` i declara:

- fabricant i noms de producte admesos;
- CPU Intel Atom x5-Z8350 de quatre nuclis;
- arquitectura x86-64;
- mínim de RAM compatible amb una configuració nominal de 2 GB;
- eMMC de 8 o 16 GB;
- gràfics Intel amb controlador `i915` i dues eixides DisplayPort;
- Ethernet gigabit;
- àudio local;
- ports/controladors USB 2.0 i USB 3.0;
- arrencada UEFI;
- sensor tèrmic opcional.

## Ordre d'inventari

```bash
.venv/bin/xaac-os --root . inspect-hardware
```

Eixida estructurada:

```bash
.venv/bin/xaac-os --root . --json inspect-hardware
```

Generació d'un informe persistent:

```bash
.venv/bin/xaac-os --root . inspect-hardware \
  --report reports/wyse3040-hardware.json
```

## Fonts de detecció

La detecció utilitza exclusivament interfícies estàndard de Linux:

- `/sys/class/dmi/id` per a fabricant i producte;
- `/proc/cpuinfo` i `/proc/meminfo`;
- `/sys/class/block/mmcblk*` per a l'eMMC;
- `/sys/bus/pci/devices` per a gràfics, àudio i USB;
- `/proc/modules` per a `i915`;
- `/sys/class/net` per a interfícies de xarxa;
- `/sys/firmware/efi` per a UEFI;
- `/sys/class/thermal` per als sensors.

No requereix `root`, no executa ordres externes i no modifica el sistema.

## Resultats i codis d'eixida

- `0`: el dispositiu compleix tots els requisits obligatoris;
- `4`: hi ha una o més incompatibilitats de maquinari;
- `2`: el perfil és invàlid o no es pot llegir.

Cada comprovació queda marcada com `pass`, `warning` o `fail`. Els sensors tèrmics
són opcionals perquè algunes revisions o firmwares poden no exposar-los al sistema.

## Proves

Les proves creen arbres `procfs` i `sysfs` simulats per validar:

- detecció completa;
- absència segura de dades;
- coincidència correcta amb el perfil;
- maquinari requerit absent;
- variants opcionals;
- perfils invàlids;
- escriptura atòmica de l'informe;
- disponibilitat de l'ordre CLI.

## Validació pendent en maquinari real

La detecció automatitzada està preparada, però la identificació definitiva dels IDs PCI,
la velocitat Ethernet i el recompte físic de connectors s'haurà de confirmar sobre un
Dell Wyse 3040 real. Aquesta validació no bloqueja la fase perquè queda explícitament
separada de les proves unitàries, tal com estableix el calendari.
