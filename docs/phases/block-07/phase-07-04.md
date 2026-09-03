# Fase 7.4 — VLAN 802.1Q

## Objectiu

Afegir configuració VLAN persistent i transaccional sobre `systemd-networkd`, disponible tant per a administració local com per a polítiques remotes de XAAC Agent/XMS.

## Implementació

- Perfil declaratiu `config/vlan.yaml`.
- Validació dels identificadors VLAN 1–4094 i dels noms d'interfície.
- Generació dels fitxers `.netdev` i `.network` de `systemd-networkd`.
- Adreçament DHCP o IPv4 estàtic per VLAN.
- Estat i diagnòstic JSON consumibles per XAAC Agent.
- Marcatge de configuració pendent durant l'aplicació.
- Snapshot i rollback transaccionals.
- Recuperació mitjançant eliminació de la VLAN i fallback a la interfície Ethernet pare.
- Escriptures atòmiques i protecció contra enllaços simbòlics.

## Ús

```bash
xaac-os --root . configure-vlan --vlan-id 100 --mode dhcp --dry-run
xaac-os --root . configure-vlan --source remote --vlan-id 200 \
  --mode static --address 192.0.2.10/24 --gateway 192.0.2.1 \
  --dns 192.0.2.53
xaac-os --root . configure-vlan --vlan-id 200 --rollback
```

La interfície pare autoritzada és `en*`. El nom predeterminat és `vlan<ID>`.

## Proves

S'han afegit proves de perfil, renderització 802.1Q, DHCP, IP estàtica, límits, polítiques, aplicació remota, idempotència, snapshot, rollback, dry-run i CLI.
