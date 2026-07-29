# Fase 4.2 — Compositor

## Objectiu

Configurar un compositor mínim i controlat per a la futura sessió XAAC Thin Client.

## Decisions

- **labwc** és el compositor Wayland principal: és lleuger, es basa en wlroots i permet configuració multimonitor.
- **Openbox** és el gestor de finestres de reserva per a una sessió X11 controlada.
- Xwayland només s'inclou com a capa de compatibilitat; no substitueix Wayland com a backend principal.
- No s'instal·len panells, llançadors, escriptoris ni menús d'usuari.

## Configuració generada

- `/etc/xaac/labwc/rc.xml`
- `/etc/xaac/labwc/autostart`
- `/etc/xaac/openbox/rc.xml`
- `/etc/xaac/session/compositor-policy.json`

Les regles forcen pantalla completa, eliminen decoracions i bloquegen dreceres i menús. El fitxer `autostart` queda reservat per a la fase 4.5.

## Ordre

```bash
xaac-os configure-compositor --dry-run
xaac-os configure-compositor
```

## Reinici segur

La política limita els reinicis a cinc intents dins d'una finestra de seixanta segons i aplica un backoff de dos segons. La supervisió efectiva del procés s'implementarà en la fase 4.6.

## Proves

Les proves cobreixen Wayland, fallback X11, doble monitor, resolució, pantalla completa, absència de panells i decoracions, límit de reinicis, idempotència i protecció de rutes.
