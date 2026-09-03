# Bloc 7 — Fase 7.2: systemd, identitats i helper privilegiat

## Objectiu

Consolidar l'execució de XAAC Agent amb privilegis mínims i preparar la frontera segura amb `xaac-kiosk` abans de definir el contracte IPC funcional de la fase 7.3.

## Decisions

- XAAC Agent continua executant-se com `xaac-agent:xaac-agent`, mai com a root.
- `xaac-agent` és membre de `xaac-command` exclusivament per connectar al socket del helper i de `xaac-ipc` per al futur contracte compartit.
- `xaac-kiosk` és membre de `xaac-ipc`, però no de `xaac-command`.
- El socket privilegiat és `root:xaac-command` mode `0660`.
- `/run/xaac-agent` és `root:xaac-command` mode `0750`; l'Agent només pot escriure a `/run/xaac-agent/runtime` mode `0700`.
- El helper valida obligatòriament `SO_PEERCRED` i només accepta l'UID real de `xaac-agent`; no hi ha override d'UID per configuració o entorn.
- El helper conserva únicament `CAP_SYS_BOOT`; `CAP_SYS_ADMIN` queda eliminada.
- El perfil de recursos de producció del Dell Wyse 3040 queda en `20-wyse-3040-resources.conf` amb `MemoryHigh=192M`, `MemoryMax=256M`, `MemorySwapMax=64M`, `TasksMax=64` i `LimitNOFILE=1024`.
- No es defineixen encara directoris ni missatges del contracte IPC; això correspon a la fase 7.3.

## Empaquetatge

La revisió Debian passa a `1.0.0-2`; la versió de l'aplicació continua sent `1.0.0`. XAAC Thin Client OS valida el paquet, els grups, els fitxers `systemd/tmpfiles`, la capacitat del helper i la pertinença de `xaac-agent` abans de continuar la construcció.
