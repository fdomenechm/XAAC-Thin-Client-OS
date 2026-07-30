# Fase 12.8 — Rendiment i estabilitat

Aquesta fase incorpora una suite reproduïble per validar la imatge de producció sobre un Dell Wyse 3040 real.

## Abast

- temps total d'arrencada;
- consum de RAM;
- càrrega de CPU;
- ocupació del disc arrel;
- temperatura del sistema;
- sessió prolongada mínima de 24 hores;
- recuperació després d'interrupcions de xarxa.

La configuració declarativa és `config/performance-stability.yaml`. L'ordre següent genera el manifest, el runner, l'esquema JSON i la guia d'execució:

```bash
xaac-os-build build-performance-tests
```

Per inspeccionar el pla sense escriure artefactes:

```bash
xaac-os-build build-performance-tests --dry-run
```

Els llindars són explícits, revisables i orientats al perfil de 2 GiB de RAM i 8 GiB d'eMMC. El runner executa totes les mètriques, conserva un informe JSON i retorna error si qualsevol llindar no es compleix.

Les mesures finals s'han d'executar sobre maquinari real, amb la imatge de producció i una sessió representativa de XAAC Thin Client.
