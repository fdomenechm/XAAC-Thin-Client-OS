# Fase 9.2 — Usuaris i permisos

## Objectiu

Consolidar els comptes del sistema i els permisos dels fitxers sensibles sota una política única de mínim privilegi.

## Implementació

El perfil `config/account-permissions.yaml` defineix:



La fase genera:

- `/usr/lib/sysusers.d/xaac-security-accounts.conf`;
- `/usr/lib/tmpfiles.d/xaac-security-permissions.conf`;
- `/etc/xaac/security/account-permissions.json`;
- `/var/lib/xaac-agent/security/account-permissions-state.json`.

## Ordres

```bash
xaac-os --root . configure-account-permissions --dry-run
xaac-os --root . configure-account-permissions
```

## Garanties



## Limitacions

Aquesta fase defineix i instal·la identitats i permisos base. El confinament dels processos mitjançant opcions de `systemd` es desenvolupa en la fase 9.3 i AppArmor en la fase 9.4.
