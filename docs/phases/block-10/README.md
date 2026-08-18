# Bloc 10 — Actualització, manteniment i recuperació

El Bloc 10 queda consolidat en cinc fases, amb una única generació d'ISO prevista al gate final sempre que cap canvi de recovery/arranc exigisca una validació física anticipada.

1. [Fase 10.1 — Arquitectura d'actualització i política de versions](phase-10-01.md)
2. [Fase 10.2 — Actualització segura i rollback](phase-10-02.md)
3. [Fase 10.3 — Manteniment i diagnòstic](phase-10-03.md)
4. [Fase 10.4 — Recuperació](phase-10-04.md)
5. [Fase 10.5 — Consolidació, proves destructives controlades i ISO final](phase-10-05.md)

## Nota sobre el codi preexistent

El repositori contenia prototips declaratius d'un full de ruta anterior del Bloc 10 amb més subfases (`update-service`, `transactional-update`, `package-rollback`, `update-rings`, `update-sources`, etc.). Els elements `transactional-update` i `package-rollback` ja han sigut absorbits per la Fase 10.2. La Fase 10.3 consolida ara el manteniment i el diagnòstic en `xaac-maintenance`. La Fase 10.4 incorpora ara un entorn de recovery local propi i deixa els prototips històrics de recovery/factory reset fora del constructor de producció. La resta continua com a material reutilitzable fins que siga incorporat explícitament a una de les cinc fases actuals.
