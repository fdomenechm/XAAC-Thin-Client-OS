# Fase 12.7 — Proves finals de maquinari

Aquesta fase prepara la validació final sobre un Dell Wyse 3040 real. No substitueix l'execució física: genera un manifest, un executor, una llista de comprovació i l'esquema de l'informe.

## Abast

- instal·lació UEFI i particions de producció;
- funcionament continu durant almenys 24 hores;
- sessió XAAC i connexió RDP;
- USB, entrada i àudio;
- actualització controlada;
- factory reset;
- recuperació local.

## Ús

```bash
xaac-os-build build-hardware-tests
sudo .build/hardware-final-tests/run-hardware-final-tests
```

Les evidències s'emmagatzemen per defecte en `/var/log/xaac/hardware-final-evidence` i l'informe en `/var/log/xaac/hardware-final-tests.json`. Les proves destructives, com el factory reset, han de seguir també la llista manual `CHECKLIST.md` en un equip de laboratori.
