# Fase 10.1 — Model d’actualització

## Objectiu

Definir un model declaratiu, validable i auditable per a les actualitzacions de XAAC Thin Client OS, sense implementar encara el repositori APT ni el servei d’instal·lació.

## Implementació

La política `config/update-model.yaml` descriu:

- els components actualitzables i el tipus de reinici requerit;
- els canals `laboratory`, `pilot` i `production` i la seua promoció;
- la finestra de manteniment en `Europe/Madrid`;
- la política SemVer, prereleases, versions mínimes i bloquejades;
- els conjunts de components que s’han de tractar de manera atòmica;
- la màquina d’estats completa des de `idle` fins a confirmació, rollback, fallada o cancel·lació.

El mòdul `update_model.py` valida referències, duplicats, versions, finestres, dependències, transicions i accessibilitat dels estats. La instal·lació genera:

- `/usr/share/xaac/update/update-model.json`, política efectiva de només lectura;
- `/var/lib/xaac-agent/update/state.json`, estat inicial auditable per a l’Agent.

Les escriptures són atòmiques, idempotents i rebutgen destinacions que siguen enllaços simbòlics.

## CLI

```bash
xaac-os --root . configure-update-model --dry-run
xaac-os --root . configure-update-model
```

## Proves

S’han incorporat proves positives, negatives, de permisos, idempotència, `dry-run`, CLI, canals, finestres, conjunts atòmics i estats inaccessibles.

## Límits de la fase

Aquesta fase només fixa el contracte del sistema d’actualització. La publicació del repositori, la comprovació remota, la descàrrega, l’staging, la verificació criptogràfica, la instal·lació i el rollback s’implementaran en les fases 10.2 a 10.8.
