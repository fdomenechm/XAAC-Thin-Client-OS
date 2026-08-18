# Bloc 10 — Actualització, manteniment i recuperació

El Bloc 10 queda consolidat en sis fases. Les cinc fases inicials cobreixen els components XAAC, manteniment, recovery i el gate de qualificació; la Fase 10.6 afegeix l'actualització controlada de la plataforma Debian 13 subjacent.

1. [Fase 10.1 — Arquitectura d'actualització i política de versions](phase-10-01.md)
2. [Fase 10.2 — Actualització segura i rollback](phase-10-02.md)
3. [Fase 10.3 — Manteniment i diagnòstic](phase-10-03.md)
4. [Fase 10.4 — Recuperació](phase-10-04.md)
5. [Fase 10.5 — Consolidació, proves destructives controlades i ISO final](phase-10-05.md)
6. [Fase 10.6 — Actualització controlada del sistema base](phase-10-06.md)

## Separació dels dos canals d'actualització

- Els paquets `xaac-thinclient`, `xaac-thin-client-vpn` i `xaac-agent` continuen actualitzant-se com un bundle XAAC signat i transaccional.
- Debian 13 s'actualitza exclusivament amb `xaac-update-admin os-check/os-update`, des de fonts `trixie` autoritzades i sense `dist-upgrade`/`full-upgrade`.

Els prototips declaratius històrics que no han sigut absorbits explícitament per aquestes sis fases continuen fora del constructor de producció.
