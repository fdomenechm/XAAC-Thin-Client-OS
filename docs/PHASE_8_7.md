# Fase 8.7 — Auditoria de sessions RustDesk

Aquesta fase incorpora un registre append-only de les sessions de XAAC Remote Support. Cada inici registra l'identificador de sessió, l'operador, el dispositiu, el motiu, l'origen i l'instant UTC. La finalització afegeix l'estat final, l'instant de tancament i la duració calculada en segons.

## Fitxers

- `config/rustdesk-session-audit.yaml`: contracte declaratiu.
- `/var/log/xaac/rustdesk-sessions.jsonl`: journal append-only.
- `/run/xaac/rustdesk/audit-active-session.json`: sessió activa efímera.
- `/var/lib/xaac-agent/services/rustdesk-audit.json`: estat consumible per XAAC Agent.

## Ordres

```bash
xaac-os-build configure-rustdesk-audit
xaac-os-build start-rustdesk-audit --session-id S1 --operator suport --device-id DEVICE --reason "Diagnòstic"
xaac-os-build end-rustdesk-audit --session-id S1 --status completed
```

Totes les ordres admeten `--dry-run`. Només es permet una sessió activa, les dates han d'incloure zona horària i el journal no es reescriu ni es trunca.
