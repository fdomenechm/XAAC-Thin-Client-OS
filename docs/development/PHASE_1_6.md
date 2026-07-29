# Fase 1.6 — Sistema de plantilles

Aquesta fase incorpora un motor mínim, segur i determinista per generar fitxers de configuració de la futura imatge Debian.

## Propietats

- expressions simples `{{ variable }}` i variables jeràrquiques;
- error explícit davant variables absents o no escalars;
- prohibició de rutes absolutes i de `..`;
- escriptura atòmica;
- renderització idempotent;
- conservació de l'estructura de directoris;
- integració amb `xaac-os prepare` i `xaac-os build`.

Les plantilles base resideixen en `templates/base/` i els resultats de cada construcció en `.build/runs/<build-id>/rendered/`.
