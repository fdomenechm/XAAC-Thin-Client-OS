# Fase 2.8 — Tallafoc base amb nftables

## Objectiu

Aplicar una política de xarxa restrictiva al sistema Debian 13 minimal abans d'incorporar la capa gràfica i el mode quiosc.

## Configuració declarativa

La política es defineix en `config/firewall.yaml`. El constructor només accepta una política d'entrada i reenviament `drop`; la sortida es manté en `accept` per permetre DHCP, DNS, actualitzacions i connexions iniciades pel Thin Client.

## Regles generades

`configure-firewall` genera `/etc/nftables.conf` amb una taula `inet` comuna per a IPv4 i IPv6. Es permeten:

- loopback;
- connexions establides o relacionades;
- client DHCPv4 i DHCPv6;
- ICMP i ICMPv6 essencials;
- SSH únicament des de les xarxes declarades en `config/ssh.yaml` i al port configurat allí.

La resta del trànsit entrant i tot el trànsit reenviat queden bloquejats per defecte.

## Activació

El servei `nftables.service` s'habilita mitjançant un enllaç a `multi-user.target.wants`. No s'intenta arrancar systemd dins del `chroot`.

## Ús

Planificació sense canvis:

```bash
.venv/bin/xaac-os --root . configure-firewall --dry-run
```

Execució real:

```bash
sudo .venv/bin/xaac-os --root . configure-firewall
```

Cal executar-la després de `configure-ssh`.

## Seguretat i traçabilitat

- validació estricta de l'esquema YAML;
- rebuig de polítiques permissives d'entrada o reenviament;
- validació de xarxes IPv4 i IPv6;
- escriptura atòmica de `/etc/nftables.conf` amb mode `0600`;
- protecció davant enllaços simbòlics;
- log en `logs/firewall-configuration.log`;
- estat i regles efectives incorporats al manifest;
- hash SHA-256 de `config/firewall.yaml`.
