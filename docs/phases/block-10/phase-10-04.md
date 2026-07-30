# Fase 10.4 — Verificació d’actualitzacions

## Objectiu

Validar tot contingut preparat en staging abans que puga arribar a la instal·lació transaccional.

## Controls

- signatura OpenPGP obligatòria del manifest amb el keyring XAAC;
- hashes SHA-256 i SHA-512 obligatoris per als artefactes;
- arquitectura `amd64`, sistema `xaac-thin-client-os` i perfil `wyse3040`;
- versió instal·lada mínima i prohibició de downgrade;
- dependències declarades, absència de cicles i respecte dels conjunts atòmics;
- estat auditable separat del servei de descàrrega.

La política és fail-closed: no existeix cap opció per ometre la signatura, relaxar els hashes, ignorar el perfil de maquinari o permetre downgrades.

## Configuració

El contracte declaratiu resideix en `config/update-verification.yaml`. La instal·lació genera:

- `/etc/xaac/update/verification.json`;
- `/var/lib/xaac-update/verification-state.json`;
- `/usr/libexec/xaac-update-verify`.

## Ús

```bash
xaac-os-build configure-update-verification --dry-run
xaac-os-build configure-update-verification
```

Aquesta fase configura el verificador i el seu contracte. La instal·lació transaccional dels paquets correspon a la fase 10.5.
