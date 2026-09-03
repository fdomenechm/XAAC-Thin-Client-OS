# Fase 12.4 — Instal·lador

## Objectiu

Preparar un instal·lador de producció segur i determinista per a XAAC Thin Client OS, destinat principalment al Dell Wyse 3040.

## Components

- `config/installer-builder.yaml`: política declarativa de seguretat, particions, còpia i GRUB UEFI.
- `xaac-os build-installer`: valida la política i genera els artefactes de l'instal·lador.
- `.build/installer/xaac-install`: instal·lador destructiu, executable únicament com a `root`.
- `.build/installer/installer.json`: configuració efectiva de la instal·lació.
- `.build/installer/summary.schema.json`: contracte del resum final.

## Flux

1. Selecció explícita del disc.
2. Confirmació exacta `INSTALL XAAC`.
3. Rebuig de discs muntats o del disc del sistema en execució.
4. Comprovació d'alimentació elèctrica i mida mínima de 7168 MiB.
5. Verificació SHA-256 de `rootfs.squashfs`.
6. Creació GPT de `XAAC_EFI`, `XAAC_ROOT`, `XAAC_DATA` i `XAAC_RECOVERY`.
7. Extracció del sistema arrel.
8. Instal·lació de GRUB UEFI amb fallback `EFI/BOOT/BOOTX64.EFI`.
9. Marca de primer inici i resum JSON final.

## Seguretat

L'instal·lador falla de manera tancada davant una selecció ambigua, una confirmació incorrecta, un disc muntat, el disc del sistema actiu, absència d'alimentació AC, espai insuficient o una font sense integritat verificable.

## Proves

Les proves cobreixen càrrega de política, manifest estable, generació, permisos, esquema del resum, idempotència, `--dry-run`, controls negatius, symlinks i CLI. No executen operacions destructives ni requereixen privilegis.
