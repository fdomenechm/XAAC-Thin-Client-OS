# Fase 1.5 — Resolució de paquets

Aquesta fase incorpora la resolució determinista de la llista efectiva de paquets que formarà cada imatge.

## Funcionalitats

- combinació ordenada dels grups `base`, `graphical`, `xaac` i `optional`;
- càrrega recursiva de l'herència de perfils;
- deduplicació de paquets entre grups i perfils;
- aplicació de les exclusions globals i de perfil;
- detecció de perfils inexistents, cicles d'herència i conflictes interns;
- ordenació estable del resultat;
- generació d'un manifest JSON serialitzable;
- integració del resultat amb `validate`, `inspect`, `prepare` i `build`.

## Ordres

```bash
.venv/bin/xaac-os --root . validate
.venv/bin/xaac-os --root . inspect
.venv/bin/xaac-os --root . --json inspect
.venv/bin/xaac-os --root . prepare
```

`inspect` mostra ara la cadena de perfils, la llista efectiva de paquets i les exclusions. El manifest de l'espai de treball incorpora la secció `packages` completa.

## Regles

1. Els perfils s'apliquen de l'ancestre més general al perfil seleccionat.
2. Un paquet repetit només apareix una vegada.
3. Les exclusions tenen prioritat sobre les inclusions heretades o globals.
4. Un mateix perfil no pot incloure i excloure explícitament el mateix paquet.
5. La llista final queda ordenada alfabèticament perquè siga reproduïble.
