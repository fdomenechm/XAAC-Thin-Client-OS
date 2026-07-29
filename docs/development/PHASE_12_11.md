# Fase 12.11 — Release candidate

Aquesta fase congela `XAAC Thin Client OS 1.0.0-rc.1` i prepara el procés verificable d'aprovació.

## Abast

- congelació funcional;
- admissió exclusiva de correccions crítiques, de seguretat, regressions provades i documentació imprescindible;
- portes de qualitat completes;
- manifest determinista de la release candidate;
- notes de versió;
- aprovació separada pels rols de responsable de release i revisor de seguretat.

## Ús

```bash
xaac-os-build build-release-candidate
.build/release-candidate/verify-rc.sh
```

La preparació no aprova la release. `approval.json` naix amb estat `pending` i bloqueja la publicació fins que el procés extern d'aprovació registre les dues conformitats requerides.
