# Fase 3.3 — Gràfics Intel

## Objectiu

Configurar i validar la GPU Intel integrada del Dell Wyse 3040, el controlador `i915`, les dues eixides DisplayPort, els modes de vídeo i l'arrencada sense monitor.

## Implementació

- Perfil declaratiu `config/graphics.yaml`.
- Detecció no privilegiada en `/sys/class/drm`, `/sys/bus/pci/devices`, `/proc/modules` i `/proc/cmdline`.
- Validació del dispositiu PCI Intel `8086` i del mòdul `i915`.
- Rebuig de `nomodeset` i `i915.modeset=0`.
- Inventari de connectors, estat, modes i activació.
- Suport d'un monitor, doble monitor, desconnexió, reconnexió i arrencada headless.
- Configuració determinista de `modules-load.d` i `modprobe.d`.
- Declaració del paquet `firmware-intel-graphics` requerit per la imatge.
- Informes JSON atòmics.

## Ordres

```bash
.venv/bin/xaac-os --root . inspect-graphics
.venv/bin/xaac-os --root . --json inspect-graphics
.venv/bin/xaac-os --root . inspect-graphics --report reports/graphics.json
.venv/bin/xaac-os --root . configure-graphics --dry-run
sudo .venv/bin/xaac-os --root . configure-graphics
```

## Limitacions

Les proves automatitzades simulen sysfs. La validació física de hotplug, doble monitor i resolucions reals s'haurà d'executar en un Dell Wyse 3040 durant les proves de maquinari.

## Resultat

La pila gràfica Intel queda descrita, detectable i configurable de manera reproduïble. La suite completa supera 350 proves.
