# Guia de desenvolupament

## Documents principals

- [Manual de desenvolupament](../manual/development.md)
- [Entorn de desenvolupament](../getting-started/development-environment.md)
- [Construcció](../getting-started/build.md)
- [Referència tècnica](../reference/README.md)
- [Bloc 8 — Acabat visual i experiència d'appliance](APPLIANCE_EXPERIENCE.md)
- [Històric de fases](../phases/README.md)

## Convencions

- Python 3.13 i estructura `src/`.
- Configuració declarativa validada abans d'aplicar-se.
- Proves per a casos positius, negatius, límits, permisos, idempotència i errors.
- Escriptures atòmiques i rebuig de rutes fora del projecte.
- Cap `.build`, caché, entorn virtual, secret o artefacte generat en el ZIP consolidat.

## Documents d'arrencada primerenca

Els fitxers `EARLY_*.md` descriuen l'ordre de configuració del rootfs durant el
bootstrap. S'han mantingut ací perquè són referència interna del constructor.

## Compatibilitat

`PHASE_1_2.md` és un enllaç editorial conservat perquè forma part de les proves
d'integritat del repositori. La documentació històrica completa és a `docs/phases/`.
