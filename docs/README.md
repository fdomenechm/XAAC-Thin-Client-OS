# Documentació de XAAC Thin Client OS

Aquesta és la documentació oficial de **XAAC Thin Client OS 1.0.0**. Està ordenada
per públic i per tipus de tasca. La documentació històrica de desenvolupament queda
separada dels manuals operatius.

## Per començar

- [Visió general i requisits](getting-started/README.md)
- [Preparació de l'entorn](getting-started/development-environment.md)
- [Construcció d'imatges i artefactes](getting-started/build.md)
- [Instal·lació al dispositiu](manual/installation.md)

## Operació i administració

- [Índex d'administració](administration/README.md)
- [Administració del sistema](manual/administration.md)
- [Xarxa](manual/network.md)
- [Seguretat](manual/security.md)
- [Actualitzacions](manual/updates.md)
- [Recuperació](manual/recovery.md)
- [Resolució de problemes](manual/troubleshooting.md)

## Disseny i manteniment

- [Arquitectura](architecture/README.md)
- [Guia de desenvolupament](development/README.md)
- [Experiència visual d'appliance](development/APPLIANCE_EXPERIENCE.md)
- [Bloc 9 — Hardening i optimització final](development/HARDENING_OPTIMIZATION.md)
- [Referència de CLI i configuració](reference/README.md)
- [Release 1.0.0](release/README.md)

## Històric

- [Fases agrupades per blocs](phases/README.md)

## Criteris editorials

1. Els manuals descriuen l'operació de la versió estable.
2. Les fases expliquen l'evolució històrica i no substitueixen els manuals.
3. Els secrets i les dades específiques d'un desplegament no formen part de la documentació.
4. Les ordres destructives sempre han d'indicar prerequisits, confirmació i recuperació.
5. Els canvis de comportament han d'actualitzar el manual afectat i el `CHANGELOG.md`.
