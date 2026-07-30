# Fase 7.6 — Perfil administrador local

## Objectiu

Proporcionar un perfil d'administració local controlat, auditable i separat de la sessió de quiosc.

## Implementació

- Compte declarat `xaac-admin` mitjançant `systemd-sysusers`.
- Directori personal restringit i grups mínims d'administració.
- Contrasenya inicial bloquejada per defecte o hash proporcionat de manera segura.
- Canvi obligatori de contrasenya en el primer inici de sessió.
- Política `sudo` limitada al menú administratiu, consulta de serveis i registres.
- Menú de consola per a diagnòstic de xarxa, serveis XAAC, logs i canvi de contrasenya.
- Regles d'auditoria per a configuració, estat i execucions privilegiades.
- Estat versionat, staging, snapshot, rollback, escriptura atòmica i protecció de symlinks.

## Ordre

```bash
xaac-os configure-local-admin --source local
```

Per establir un hash inicial SHA-512 o yescrypt:

```bash
xaac-os configure-local-admin --password-hash '$6$...'
```

La contrasenya en text pla no és acceptada. També estan disponibles `--dry-run` i `--rollback`.

## Limitacions

La creació efectiva del compte, la càrrega de regles d'auditoria i la validació interactiva del canvi de contrasenya s'han de provar en la imatge Debian o en maquinari real.
