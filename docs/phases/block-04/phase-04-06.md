# Fase 4.6 — Supervisió de la sessió

## Objectiu

Mantindre XAAC Thin Client disponible davant de fallades, sense crear bucles infinits ni ocultar un estat degradat persistent.

## Implementació

- Supervisor únic `/usr/local/libexec/xaac-session-supervisor`.
- Reinici automàtic només davant d'eixides no voluntàries.
- Màxim de cinc reinicis dins d'una finestra de 60 segons.
- Backoff exponencial entre 2 i 30 segons.
- Reinicialització del comptador després de 300 segons d'execució estable.
- Estat atòmic en `/run/user/xaac-kiosk/xaac-session-supervisor.json`.
- Pantalla GTK 4 a pantalla completa quan se supera el límit.
- Notificació best effort a l'Agent mitjançant socket Unix, sense convertir l'absència de l'Agent en una nova fallada.
- Integració amb l'autostart de labwc, que inicia el supervisor en lloc del client directament.

## Ordres

```bash
xaac-os configure-session-supervisor --dry-run
xaac-os configure-session-supervisor
```

## Límits

La integració funcional amb XAAC Thin Client Agent es completarà en el bloc 6. En aquesta fase només queda definit el contracte local d'esdeveniments i la degradació segura.
