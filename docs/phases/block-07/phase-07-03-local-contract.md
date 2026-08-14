# Bloc 7 — Fase 7.3: contracte local OS ↔ Agent

## Objectiu

Definir una única frontera local, versionada i de privilegis mínims entre XAAC Thin Client OS, el supervisor de sessió i XAAC Agent, sense inventar un servei systemd per al Thin Client ni mantindre sockets sense consumidor.

## Contracte

El contracte és `xaac-local-integration/v1`. XAAC Thin Client 1.0.x publica estat `xaac-state/v2` i events `xaac-local-event/v1`. L'Agent conserva lectura de `xaac-state/v1` només com a compatibilitat de migració.

| Ruta | Propietari | Mode | Direcció |
|---|---|---:|---|
| `/var/lib/xaac/thin-client/state` | `xaac-kiosk:xaac-ipc` | `2750` | quiosc → Agent |
| `/run/xaac/thin-client/events` | `xaac-kiosk:xaac-ipc` | `2750` | supervisor → Agent |
| `/var/lib/xaac/thin-client/config` | `xaac-agent:xaac-ipc` | `2750` | Agent → Thin Client |
| `/run/xaac/commands` | `xaac-agent:xaac-ipc` | `2750` | Agent → Thin Client |

El bit setgid manté el grup `xaac-ipc` en els fitxers nous. Cap dels dos processos rep escriptura sobre els directoris propietat de l'altre. `xaac-kiosk` continua fora de `xaac-command`.

## Supervisor de sessió

El supervisor escriu `state.json` de manera atòmica, refresca el heartbeat cada 30 segons mentre el client viu i publica els canvis de cicle de vida com a events JSON. La retenció es limita a 128 events. L'Agent és consumidor de només lectura dels events i no els elimina.

RDP es publica com `unknown` perquè el supervisor no disposa d'eixa informació. La informació RDP s'afegirà quan XAAC Thin Client la publique explícitament.

## Eliminacions

- `config/ipc.yaml` i `ipc_configuration.py`;
- `/run/xaac/agent.sock`;
- `/run/xaac-agent/session-events.sock`;
- dependència `socat` per a notificacions de sessió.

## Empaquetatge

XAAC Agent passa a la revisió Debian `1.0.0-3`, mantenint la versió d'aplicació `1.0.0`. XAAC Thin Client OS valida el contracte, els propietaris/modes i l'artefacte Agent abans de construir la ISO.
