# Fase 5.1 — Model de restriccions

Aquesta fase inicia el Bloc 5 amb un model de seguretat explícit i auditable per a la sessió `xaac-kiosk`. La política adopta **deny by default** i descriu què pot fer cada actor abans d’implementar els mecanismes d’enforcement de les fases següents.

## Abast

- model d’amenaces del mode quiosc;
- accions expressament autoritzades;
- política de dreceres;
- llista base de processos autoritzats i prohibits;
- política per classes de dispositiu;
- sessions gràfiques, TTY i remotes;
- generació separada de la política efectiva i del model d’amenaces.

La propietat `enforcement_mode: staged` és deliberada: la Fase 5.1 defineix i valida el contracte, però no afirma que tots els controls estiguen ja aplicats. El bloqueig efectiu correspon a les fases 5.2–5.7.

## Ordres

```bash
xaac-os configure-kiosk-restrictions --dry-run
xaac-os configure-kiosk-restrictions
```

## Fitxers generats

- `/etc/xaac/kiosk/restrictions.json`, mode `0640`;
- `/usr/share/doc/xaac-thin-client-os/kiosk-threat-model.json`, mode `0644`.

## Validacions

La càrrega rebutja polítiques permissives, superfícies sense cobertura, identificadors duplicats, dreceres o processos contradictoris, automuntatge, accés del quiosc a TTY/SSH, canvi de sessió i rutes insegures. L’escriptura és atòmica, idempotent i no segueix enllaços simbòlics de destinació.

## Limitacions conegudes

Aquesta fase no bloqueja encara dreceres, terminals, TTY, dispositius ni accions d’apagada. Únicament estableix la font de veritat que les fases posteriors consumiran.
