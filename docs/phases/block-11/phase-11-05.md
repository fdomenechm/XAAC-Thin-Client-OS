# Fase 11.5 — Partició de recuperació

Aquesta fase defineix i instal·la la configuració d'una partició local protegida, identificada amb l'etiqueta `XAAC_RECOVERY`.

Inclou una imatge SquashFS immutable i signada, kernel i initramfs dedicats, eines mínimes de diagnòstic i reparació, muntatge només de lectura i verificació *fail-closed* en cada arrencada.

```bash
xaac-os --root . configure-recovery-partition --dry-run
xaac-os --root . configure-recovery-partition
```

La fase només prepara els artefactes i contractes del sistema. La construcció física de la partició i de la imatge es completarà en els constructors d'imatges del bloc 12.
