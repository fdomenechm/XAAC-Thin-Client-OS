# Fase 6.5 — IPC Client-Agent

## Objectiu

Definir i instal·lar el canal local entre XAAC Thin Client i XAAC Thin Client Agent amb autenticació, esquema de missatges, control d'errors i versionat.

## Decisió d'arquitectura

S'ha seleccionat un **socket Unix** en `/run/xaac/agent.sock` en lloc de D-Bus. El canal és privat, lleuger i adequat per al Dell Wyse 3040. L'Agent valida les credencials del procés client mitjançant `SO_PEERCRED`; per tant, no es confia en identificadors declarats dins del missatge.

El grup `xaac-ipc` delimita els processos que poden obrir el socket. El client de quiosc i l'Agent mantenen comptes separats.

## Protocol local v1

Cada missatge és un objecte JSON delimitat per salt de línia amb els camps exactes:

- `type`;
- `request_id`;
- `version`;
- `payload`.

La versió inicial autoritza `ping`, `get_status`, `power_action` i `report_client_state`. Els tipus desconeguts, versions incompatibles, missatges malformats i càrregues superiors a 64 KiB es rebutgen.

## Instal·lació

```bash
xaac-os --root . configure-ipc --dry-run
xaac-os --root . configure-ipc
```

S'instal·len:

- `/etc/xaac/ipc.yaml`;
- `/usr/lib/tmpfiles.d/xaac-ipc.conf`;
- `/etc/xaac/ipc-manifest.json`.

`systemd-tmpfiles` crea `/run/xaac` amb mode `0750`, propietari `xaac-agent` i grup `xaac-ipc`. El socket tindrà mode `0660`.

## Seguretat i limitacions

Aquesta fase defineix el contracte, la serialització, la verificació de credencials i la configuració del canal. La integració dels bucles servidor/client dins dels paquets XAAC es completarà en els repositoris respectius; el sistema operatiu no concedeix execució arbitrària ni incorpora cap missatge de tipus shell.
