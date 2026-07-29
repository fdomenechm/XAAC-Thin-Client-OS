# Fase 12.12 — Release 1.0.0

## Objectiu

Tancar el Bloc 12 i preparar la primera versió estable de XAAC Thin Client OS per al Dell Wyse 3040.

## Implementació

La fase incorpora `config/final-release.yaml`, el mòdul `final_release.py` i l'ordre `build-final-release`. El procés exigeix l'aprovació prèvia de la release candidate, comprova tots els artefactes finals, genera `SHA256SUMS`, crea signatures OpenPGP separades i consolida el manifest, les notes i l'anunci de publicació.

Els artefactes previstos són ISO, IMG, recovery IMG, paquet PXE, repositori de paquets Debian i documentació. La versió del projecte queda fixada en `1.0.0`.

## Execució

```bash
xaac-os-build build-final-release --dry-run
xaac-os-build build-final-release
.build/final-release/publish-release.sh
.build/final-release/verify-release.sh
```

La publicació real necessita `XAAC_SIGNING_KEY`, els artefactes construïts i `.build/release-candidate/approval.json` en estat aprovat.

## Limitacions

La suite valida la preparació de la release, però no fabrica ISO/IMG ni signa artefactes durant els tests. Eixes operacions requereixen les eines del constructor, una clau privada autoritzada i els artefactes finals reals.
