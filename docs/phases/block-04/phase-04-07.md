# Fase 4.7 — Multimonitor i escalat

Configura una política declarativa per a disposició estesa, monitor principal, resolucions, escalat mixt, connexió en calent i integració FreeRDP. Wayland usa `wlr-randr`; X11 queda com a alternativa controlada amb `xrandr`.

```bash
xaac-os configure-display-layout --dry-run
xaac-os configure-display-layout
```

La política genera scripts idempotents, un servei d'usuari per reconciliar eixides i variables `/multimon` i `/dynamic-resolution` per a FreeRDP.
