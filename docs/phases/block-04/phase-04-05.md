# Fase 4.5 — Llançament de XAAC Thin Client

## Objectiu

Preparar un llançament determinista i segur de XAAC Thin Client dins de la sessió gràfica dedicada.

## Implementació

- Llançador únic `/usr/local/libexec/xaac-thin-client-launch`.
- Entorn virtual fixat a Python 3.13 en `/opt/xaac-thin-client/.venv`.
- Validació prèvia de l'intèrpret, directori d'aplicació i configuració.
- Execució com a mòdul Python amb configuració explícita.
- Bloqueig amb `flock` per evitar processos duplicats.
- Variables d'entorn GTK/Wayland i Python sense bytecode.
- Eixida estàndard preparada per a captura en journald per la sessió.
- Integració amb l'autostart de labwc.

## Ordres

```bash
xaac-os configure-thin-client-launcher --dry-run
xaac-os configure-thin-client-launcher
```

## Límits

La política avançada de reinici, backoff, pantalla d'error i notificació a l'Agent correspon a la fase 4.6.
