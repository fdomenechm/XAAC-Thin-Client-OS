# Fase 7.2 — DHCP i IP estàtica

## Objectiu

Proporcionar configuració IPv4 local i remota sobre `systemd-networkd`, amb validació estricta, fallback DHCP i restauració transaccional de l'última configuració.

## Implementació

- Perfil declaratiu `config/ip-addressing.yaml`.
- Fonts autoritzades `local` i `remote`.
- DHCP IPv4 com a mode predeterminat i fallback segur.
- IPv4 estàtica amb prefix, passarel·la i fins a tres servidors DNS.
- Validació de sintaxi, família IP i pertinença de la passarel·la a la subxarxa.
- Estat persistent per a XAAC Agent.
- Fitxer de transacció pendent durant l'aplicació.
- Snapshots previs amb retenció limitada.
- Rollback explícit a l'últim snapshot.
- Escriptures atòmiques, permisos restrictius i protecció contra enllaços simbòlics.

## Ordres

```bash
xaac-os configure-ip-addressing --mode dhcp
xaac-os configure-ip-addressing --source remote --mode static \
  --address 192.0.2.10/24 --gateway 192.0.2.1 --dns 192.0.2.53
xaac-os configure-ip-addressing --rollback
```

Totes les variants admeten `--dry-run`.

## Limitacions de la fase

La verificació de connectivitat posterior i la confirmació remota temporitzada es desenvoluparan amb el diagnòstic i les polítiques de xarxa de les fases posteriors. En aquesta fase el rollback és explícit i sempre conserva DHCP com a fallback declarat.
