# Fase 11.4 — Mode de recuperació local

Aquesta fase incorpora una entrada GRUB dedicada que inicia `xaac-recovery.target`, un entorn mínim autenticat i un menú restringit de recuperació.

La xarxa està desactivada per defecte i només es pot activar explícitament sobre Ethernet. Totes les accions queden registrades de manera persistent. Les accions destructives requereixen confirmació i el `factory reset` automàtic està prohibit.

## Instal·lació

```bash
xaac-os --root . configure-local-recovery --dry-run
xaac-os --root . configure-local-recovery
```
