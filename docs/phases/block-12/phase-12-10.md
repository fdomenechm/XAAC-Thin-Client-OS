# Fase 12.10 — Packaging i repositoris

Aquesta fase consolida els paquets Debian de XAAC Thin Client, Agent, RustDesk i el metapaquet `xaac-thin-client-os`. El perfil `config/production-packaging.yaml` defineix arquitectura, fonts, canals `laboratory`, `pilot` i `production`, signatura obligatòria i eixides.

L'ordre `xaac-os-build build-production-packaging` genera un manifest determinista, una configuració de distribucions per a `reprepro` i un script de publicació que exigeix una clau OpenPGP explícita. El mode `--dry-run` valida sense escriure artefactes.
