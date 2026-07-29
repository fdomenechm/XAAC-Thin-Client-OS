# Fase 5.2 — Bloqueig de dreceres

Aquesta fase aplica el primer control efectiu del model de restriccions definit en la Fase 5.1. La sessió `xaac-kiosk` passa a tindre una política de teclat **deny by default** tant en Wayland amb labwc com en el fallback X11 amb Openbox.

## Abast

- bloqueig del canvi d’aplicació;
- bloqueig del tancament de finestres;
- eliminació dels menús del compositor;
- bloqueig de l’execució ràpida i dels llançadors;
- bloqueig de captures de pantalla;
- bloqueig de dreceres de sistema;
- conservació de `Ctrl+Alt+F12` com a combinació reservada per a la futura política de TTY administratiu de la Fase 5.4.

## Implementació

La política `config/shortcut-lockdown.yaml` classifica totes les combinacions prohibides i exigeix `enforcement_mode: enforce`. El configurador genera configuracions completes i deterministes per als dos backends gràfics:

- labwc sense `<default />` i amb `<keyboard />` buit;
- Openbox amb `<keyboard />` buit;
- menú arrel desactivat en ambdós backends;
- política efectiva JSON restringida a mode `0640`.

L’eliminació explícita de les dreceres predeterminades és necessària perquè labwc podria carregar combinacions pròpies encara que la política declarativa les considerara prohibides.

## Ordres

```bash
xaac-os configure-shortcut-lockdown --dry-run
xaac-os configure-shortcut-lockdown
```

## Fitxers generats

- `/etc/xaac/labwc/rc.xml`, mode `0644`;
- `/etc/xaac/openbox/rc.xml`, mode `0644`;
- `/etc/xaac/kiosk/shortcut-policy.json`, mode `0640`.

## Validacions

Es rebutgen polítiques permissives, backends incomplets, dreceres duplicades, categories absents, contradiccions amb dreceres reservades, rutes insegures i destinacions que siguen enllaços simbòlics. L’escriptura és atòmica i idempotent.

## Limitacions conegudes

La fase bloqueja dreceres del compositor i del gestor de finestres, però no implementa encara el control de TTY, terminals instal·lats, URI, processos arbitraris ni accions d’apagada. Aquests controls corresponen a les fases 5.3, 5.4 i 5.7.
