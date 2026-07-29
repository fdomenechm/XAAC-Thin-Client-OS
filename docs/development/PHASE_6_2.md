# Fase 6.2 — Paquet XAAC Agent

Aquesta fase integra el paquet Debian de XAAC Thin Client Agent dins del rootfs.

## Abast

- validació del `.deb`, versió, arquitectura, dependències i SHA-256;
- compte de sistema `xaac-agent` sense shell interactiva;
- directoris persistents `/var/lib/xaac-agent` i `/var/log/xaac-agent`;
- configuració inicial en `/etc/xaac/agent/agent.yaml`;
- unitat `xaac-agent.service`, habilitada en `multi-user.target`;
- permisos restrictius i hardening systemd inicial;
- instal·lació idempotent i protecció contra enllaços simbòlics.

## Ordres

```bash
xaac-os --root . install-xaac-agent --dry-run
xaac-os --root . install-xaac-agent
```

L'artefacte de producció no forma part del ZIP consolidat. S'ha de publicar com
`packages/xaac-agent_1.0.0_amd64.deb` abans d'una construcció real.
