# Fase 7.3 — DNS, NTP i proxy

Aquesta fase configura els serveis corporatius de resolució, sincronització horària i eixida HTTP/HTTPS.

## Implementació

- `systemd-resolved` com a backend DNS.
- Servidors DNS i dominis de cerca validats.
- DNSSEC en mode `allow-downgrade` i DNS-over-TLS oportunista.
- `systemd-timesyncd` amb servidors NTP configurables i fallback Debian.
- Proxy HTTP/HTTPS global i configuració APT equivalent.
- Excepcions `NO_PROXY` i regles `DIRECT` d'APT.
- Origen local o remot per a integració amb XAAC Agent/XMS.
- Estat i diagnòstic JSON versionats.
- Snapshot i rollback de l'última configuració.

## Ordres

```bash
xaac-os --root . configure-network-services \
  --dns 192.0.2.53 --domain example.org \
  --ntp ntp.example.org \
  --proxy http://proxy.example.org:3128 \
  --no-proxy localhost --no-proxy example.org

xaac-os --root . configure-network-services --rollback
```

Totes les variants admeten `--dry-run`.
