# Fase 10.6 — Rollback de paquets

Aquesta fase defineix el rollback segur d'una transacció d'actualització fallida.

## Abast

- exigeix una transacció fallida, un punt de recuperació i versions anteriors disponibles;
- restaura paquets, configuració i estat transaccional;
- reinicia només els serveis afectats i autoritzats;
- valida el resultat de manera `fail-closed`;
- registra i bloqueja la versió defectuosa amb motiu i identificador de transacció;
- conserva evidències per al diagnòstic i l'auditoria.

## Configuració

La política es troba en `config/package-rollback.yaml`. La instal·lació genera:

- `/etc/xaac/update/package-rollback.json`;
- `/var/lib/xaac-update/rollback-state.json`;
- `/usr/libexec/xaac-update-rollback-packages`;
- `/etc/systemd/system/xaac-update-rollback.service`.

## CLI

```bash
xaac-os-build configure-package-rollback --dry-run
xaac-os-build configure-package-rollback
```

La fase no implementa encara els anells de desplegament, que corresponen a la fase 10.7.
