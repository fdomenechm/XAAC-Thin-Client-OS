# Fase 12.9 — Documentació

Aquesta fase consolida la documentació de producció de XAAC Thin Client OS.

## Manuals
- instal·lació;
- administració;
- xarxa;
- seguretat;
- actualització;
- recuperació;
- desenvolupament;
- resolució de problemes.

La configuració `config/documentation.yaml` declara el conjunt obligatori. L’ordre següent valida els manuals i genera l’índex i el manifest determinista:

```bash
xaac-os-build build-documentation
```

Per inspeccionar el pla sense escriure artefactes:

```bash
xaac-os-build build-documentation --dry-run
```
