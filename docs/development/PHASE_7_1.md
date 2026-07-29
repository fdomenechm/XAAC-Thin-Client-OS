# Fase 7.1 — Gestor de xarxa

## Objectiu

Seleccionar i configurar definitivament el gestor de xarxa base de XAAC Thin Client OS, assegurar la gestió Ethernet i exposar un estat estable i versionat a XAAC Thin Client Agent.

## Decisió tècnica

S'adopta **systemd-networkd** com a backend definitiu perquè ja forma part de systemd, té una petjada reduïda i és adequat per al Dell Wyse 3040 amb 2 GB de RAM. La configuració és exclusiva: no s'instal·la ni s'activa NetworkManager, ConnMan o altres gestors competidors.

## Implementació

- Perfil declaratiu `config/network-manager.yaml`.
- Configuració Ethernet base sobre interfícies `en*`.
- DHCP IPv4, IPv6 link-local i espera de connectivitat.
- Activació de `systemd-networkd` i `systemd-networkd-wait-online`.
- Manifest auditable en `/etc/xaac/network-manager.json`.
- Estat versionat per a l'Agent en `/run/xaac-agent/network/status.json`.
- Fitxer d'entorn i drop-in de systemd per a `xaac-agent.service`.
- Ordre `xaac-os configure-network-manager` amb `--dry-run`.

## Contracte d'estat amb l'Agent

El fitxer d'estat usa el format `xaac-network-status`, versió 1. Inicialment queda en estat `unknown`; l'Agent podrà actualitzar-lo o observar-lo sense haver d'interpretar fitxers interns de systemd-networkd.

## Seguretat i idempotència

Les rutes han de ser absolutes i no poden contindre `..`. No se sobreescriuen enllaços simbòlics. Les escriptures són atòmiques i una segona execució produeix el mateix resultat.

## Proves

S'han afegit proves de perfil, backend no admés, rootfs insegur, renderització Ethernet, dry-run, instal·lació, integració amb l'Agent, idempotència, enllaços simbòlics i CLI.

## Limitacions

La fase estableix el gestor i el contracte d'estat. L'adreçament estàtic, DNS/NTP/proxy, VLAN i IEEE 802.1X corresponen a les fases 7.2 a 7.5.
