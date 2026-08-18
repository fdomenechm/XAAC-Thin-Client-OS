# Recuperació

Els recursos de recuperació de producció del Bloc 10 es defineixen en `config/recovery-environment.yaml`, `src/xaac_thin_client_os/recovery_environment.py` i `assets/runtime/xaac-recovery`.

La Fase 10.4 proporciona un target systemd mínim, una entrada GRUB, rollback transaccional, reparació de `dpkg`/initramfs/GRUB i restauració de configuració. No habilita factory reset perquè encara no existeix una imatge factory independent i signada a la partició de recuperació.

Alguns mòduls antics de recovery continuen versionats com a prototips del full de ruta anterior, però no estan integrats en el `ProductionIsoBuilder` i no s'han de considerar mecanismes de producció.

Consulteu [docs/manual/recovery.md](../docs/manual/recovery.md) i [Fase 10.4](../docs/phases/block-10/phase-10-04.md).
