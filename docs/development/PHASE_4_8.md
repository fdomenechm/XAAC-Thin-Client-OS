# Fase 4.8 — Validació de sessió gràfica

Aquesta fase tanca el bloc 4 amb una política reproduïble per validar l'arrencada completa de la sessió XAAC, els límits de consum i temps, l'estabilitat de systemd i l'absència d'escriptoris convencionals o terminals accessibles.

## Ordre

```bash
xaac-os validate-graphical-session --dry-run
xaac-os validate-graphical-session
```

La validació física completa s'ha d'executar dins de la imatge Debian 13 o sobre el Dell Wyse 3040. Les proves unitàries validen la política, els casos límit, la idempotència i la generació segura dels artefactes.
