# Bloc 5 — Integració definitiva de XAAC Thin Client

Aquest bloc consolida la cadena d'arrencada gràfica real de la imatge de producció:

`greetd → xaac-kiosk → xaac-session → labwc/Openbox → xaac-session-supervisor → XAAC Thin Client`

## Garanties implementades

- inici automàtic de la sessió dedicada `xaac-kiosk` mitjançant `greetd`;
- Wayland amb `labwc` com a backend principal;
- fallback controlat a X11 amb `startx` i `openbox`, sense escolta TCP;
- pantalla d'espera GTK 4 a pantalla completa durant l'arrencada del client;
- supervisió del procés, reinicis amb backoff i pantalla d'error segura;
- autostart únic a través del supervisor, sense llançaments duplicats;
- absència de panells, menús, decoracions, escriptoris i terminals gràfics;
- aplicació efectiva dels plans al `rootfs` del constructor de la ISO de producció;
- exclusió de `greetd` quan la ISO arranca en mode instal·lador.

## Verificació

```bash
python -m pytest -q
sudo ./scripts/build-production-iso.sh --clean
```

En una instal·lació final, `graphical.target` és l'objectiu predeterminat i `greetd.service` queda habilitat. En mode instal·lador (`xaac.mode=installer`) la condició systemd impedeix que `greetd` competisca amb l'instal·lador de la TTY1.
