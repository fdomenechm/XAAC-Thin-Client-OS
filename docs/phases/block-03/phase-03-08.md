# Fase 3.8 — Optimització de RAM i disc

## Objectiu

Adaptar Debian 13 als 2 GB de RAM i 8 GB d'eMMC del Dell Wyse 3040, reduint pressió de memòria, ocupació persistent i escriptures innecessàries.

## Implementació

- zram al 50% de la RAM amb `zstd` i prioritat 100;
- `vm.swappiness=100` i `vm.page-cluster=0`;
- journald volàtil limitat a 32 MiB;
- `/tmp` en tmpfs limitat a 128 MiB;
- política `noatime` per al sistema arrel;
- neteja automàtica de `/tmp` i `/var/tmp` després de 7 dies;
- desactivació d'`apt-daily`, `apt-daily-upgrade` i `man-db.timer`;
- informe d'inventari de memòria, swap, zram, espai lliure, opcions de muntatge i journald.

## Ordres

```bash
xaac-os inspect-resources
xaac-os inspect-resources --report reports/resources.json
xaac-os configure-resources --dry-run
xaac-os configure-resources
```

## Validació pendent en maquinari real

Cal mesurar consum en repòs i durant RDP, pressió de memòria, activació d'OOM, escriptures reals sobre eMMC, espai lliure i estabilitat prolongada.
