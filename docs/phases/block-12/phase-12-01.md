# Fase 12.1 — Constructor ISO

## Objectiu

Preparar de forma reproduïble la ISO híbrida de producció de XAAC Thin Client OS per a `amd64` i el perfil Dell Wyse 3040.

## Funcionalitats

- ISO híbrida compatible amb UEFI i arrencada BIOS de compatibilitat.
- GRUB 2 amb entrada d’instal·lació per defecte.
- Mode live separat, de només lectura i exclusivament orientat al diagnòstic.
- Incorporació controlada del kernel, initramfs, SquashFS i llançador de l’instal·lador.
- Generació SHA-256 de la ISO.
- Signatura OpenPGP separada, obligatòria i sense incloure claus privades al projecte.
- Manifest estable de construcció.
- Script de construcció fail-closed amb comprovació prèvia de totes les fonts.

## Configuració

La política es troba en `config/iso-builder.yaml`. Les rutes són relatives al projecte i no poden escapar de l’arrel.

## Ús

```bash
.venv/bin/xaac-os --root . build-iso --dry-run
.venv/bin/xaac-os --root . build-iso
.build/iso/build-iso.sh
```

La primera ordre valida i mostra els artefactes previstos. La segona prepara l’arbre ISO, el menú GRUB, el manifest i el script final. L’última construeix, calcula el hash i signa la ISO; requereix `xorriso`, `gpg` i els artefactes previs de la imatge.

## Seguretat

- El mode diagnòstic no permet instal·lar ni obrir una shell.
- No es permet persistència des del mode live.
- La construcció falla si falta qualsevol font.
- Les destinacions amb enllaços simbòlics són rebutjades.
- La signatura és obligatòria i usa només l’identificador públic configurat.

## Proves

`tests/test_iso_builder.py` cobreix configuració vàlida, manifest, UEFI, BIOS híbrid, instal·lador, mode diagnòstic, signatura, hash, idempotència, dry-run, rutes insegures, symlinks i CLI.
