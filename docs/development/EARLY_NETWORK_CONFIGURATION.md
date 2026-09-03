# Fase 2.6 — Xarxa mínima del sistema

## Objectiu

Configurar una xarxa Ethernet mínima i reproduïble dins del rootfs Debian 13, adequada per al Dell Wyse 3040 i sense incorporar gestors gràfics de xarxa.

## Configuració declarativa

`config/network.yaml` defineix el backend, el patró d'interfície, DHCP, IPv6 i la resolució DNS. La implementació inicial utilitza exclusivament `systemd-networkd` i, opcionalment, `systemd-resolved`.

La configuració predeterminada:

- aplica a interfícies Ethernet amb nom `en*`;
- obté IPv4 mitjançant DHCP;
- no activa DHCPv6 ni Router Advertisements;
- espera que la xarxa estiga disponible durant l'arrencada;
- utilitza el DNS anunciat per DHCP;
- no fixa servidors DNS externs.

## Fitxers generats

- `/etc/systemd/network/20-xaac-wired.network`
- `/etc/systemd/resolved.conf.d/20-xaac.conf`
- `/etc/resolv.conf`, com a enllaç al stub de `systemd-resolved`
- enllaços d'activació dins de `multi-user.target.wants`

## Ús

Planificació sense canvis:

```bash
.venv/bin/xaac-os --root . configure-network --dry-run
```

Execució real:

```bash
sudo .venv/bin/xaac-os --root . configure-network
```

Cal executar-la després de configurar els usuaris del rootfs.

## Seguretat i traçabilitat

- validació estricta de l'esquema YAML;
- validació d'adreces DNS amb `ipaddress`;
- escriptura atòmica i permisos `0644`;
- rebuig d'enllaços simbòlics inesperats als fitxers regulars;
- comprovació de privilegis i de les unitats systemd requerides;
- log en `logs/network-configuration.log`;
- configuració i resultat incorporats al manifest verificable;
- `config/network.yaml` inclòs en els hashes de fonts.
