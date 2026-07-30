# Fase 8.8 — Validació de RustDesk amb mode quiosc

## Objectiu

Tancar el Bloc 8 amb un contracte reproduïble per validar XAAC Remote Support dins de la sessió de quiosc, sense confondre proves unitàries amb validacions reals de sessió o maquinari.

## Cobertura

La política `config/rustdesk-kiosk-validation.yaml` exigeix:

- captura funcional amb PipeWire/portal en Wayland o mecanisme X11;
- entrada de teclat i punter mitjançant `uinput` o X11;
- un o dos monitors i reconfiguració dinàmica;
- comprovació separada de Wayland i X11;
- bloqueig de terminal, canvi d'aplicació, tancament del quiosc i menú de sistema;
- llindars de temps d'inici, RSS, CPU activa i latència d'entrada.

## Ordres

```bash
xaac-os --root . configure-rustdesk-kiosk-validation
xaac-os --root . validate-rustdesk-kiosk --evidence /path/evidence.json
```

`--dry-run` valida el perfil i l'evidència sense escriure el rootfs.

## Evidència

El fitxer JSON d'evidència ha de contindre exactament `capture`, `input`, `multimonitor`, `backends`, `lockdown` i `performance`. El resultat es publica en:

- `/var/lib/xaac-agent/rustdesk/kiosk-validation-report.json`;
- `/var/lib/xaac-agent/rustdesk/kiosk-validation-state.json`.

## Limitacions

Les proves automatitzades validen l'esquema, les regles, els llindars, els permisos i la CLI. La captura real, la injecció d'entrada, el canvi en calent de monitors i el rendiment s'han d'executar en una sessió gràfica real i, preferentment, en un Dell Wyse 3040. El sistema no declara aquestes comprovacions com a superades sense evidència explícita.
