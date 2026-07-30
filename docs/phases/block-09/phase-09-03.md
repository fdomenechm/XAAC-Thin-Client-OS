# Fase 9.3 — Hardening systemd

Aquesta fase aplica una política declarativa de mínim privilegi als serveis XAAC.

## Controls

- `NoNewPrivileges=yes`.
- `ProtectSystem=strict` i `ProtectHome=yes`.
- protecció del kernel, mòduls i cgroups;
- namespaces restringits;
- `CapabilityBoundingSet` mínim per servei;
- `DevicePolicy=closed` i excepcions explícites;
- famílies d'adreces limitades;
- filtre de syscalls basat en `@system-service`, amb muntatge, reinici i swap bloquejats;
- rutes d'escriptura declarades per servei.

## Execució

```bash
xaac-os --root . configure-systemd-hardening --dry-run
xaac-os --root . configure-systemd-hardening
```

Els fragments es generen en `/etc/systemd/system/<unit>.d/90-xaac-hardening.conf`. La política efectiva i l'estat auditable queden disponibles per a XAAC Agent.

## Limitació coneguda

La compatibilitat final dels filtres de syscalls i dels dispositius permesos s'haurà de validar sobre la imatge Debian 13 i el Dell Wyse 3040 real abans del mode `enforce` definitiu.
