# Fase 5.3 — Bloqueig de terminals

## Objectiu

Impedir que l’usuari de quiosc execute terminals, intèrprets, ordres arbitràries, llançadors o URI no autoritzats.

## Implementació

- Política declarativa `config/terminal-lockdown.yaml`.
- Exclusió explícita dels emuladors de terminal comuns en `config/packages.yaml`.
- Llista d’executables i intèrprets prohibits.
- Prohibició de llançadors `.desktop` creats per l’usuari.
- Restricció dels esquemes URI a `xaac`.
- Desactivació dels obridors genèrics mitjançant `mimeapps.list`.
- `PATH` mínim limitat als directoris interns de XAAC.
- Generació de política efectiva JSON auditable.
- Escriptura atòmica, idempotent i protegida contra enllaços simbòlics.

## Ordres

```bash
xaac-os configure-terminal-lockdown --dry-run
xaac-os configure-terminal-lockdown
```

## Fitxers generats

- `/etc/xaac/kiosk/environment.d/20-terminal-lockdown.conf`
- `/etc/xaac/kiosk/mimeapps.list`
- `/etc/xaac/kiosk/terminal-lockdown.json`

## Proves

Les proves cobreixen:

- validació positiva i negativa de la política;
- absència dels paquets prohibits;
- generació del `PATH` restringit;
- restricció d’URI;
- idempotència;
- escriptura atòmica;
- protecció contra rutes insegures i enllaços simbòlics;
- disponibilitat de l’ordre CLI.

## Limitacions

Aquesta fase defineix i instal·la els controls de terminals, llançadors, URI i `PATH`. El control dels TTY correspon a la Fase 5.4 i el sistema de fitxers efímer del quiosc correspon a la Fase 5.5.
