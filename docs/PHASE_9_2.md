# Fase 9.2 — Usuaris i permisos

## Objectiu

Consolidar els comptes del sistema i els permisos dels fitxers sensibles sota una política única de mínim privilegi.

## Implementació

El perfil `config/account-permissions.yaml` defineix:

- `root`, bloquejat per a accés remot i reservat a recuperació local;
- `xaac-admin`, amb accés interactiu controlat i `sudo` restringit per la fase 7.6;
- `xaac-kiosk`, sense shell interactiva i només amb els grups de dispositiu necessaris;
- `xaac-agent`, com a compte de servei sense login;
- `xaac-rustdesk`, com a compte de servei separat i sense login;
- els grups de sistema XAAC;
- regles explícites de separació de privilegis;
- propietari, grup i mode dels directoris sensibles.

La fase genera:

- `/usr/lib/sysusers.d/xaac-security-accounts.conf`;
- `/usr/lib/tmpfiles.d/xaac-security-permissions.conf`;
- `/etc/xaac/security/account-permissions.json`;
- `/var/lib/xaac-agent/security/account-permissions-state.json`.

## Ordres

```bash
xaac-os --root . configure-account-permissions --dry-run
xaac-os --root . configure-account-permissions
```

## Garanties

- definició exacta dels cinc comptes obligatoris;
- comptes de quiosc i servei amb `/usr/sbin/nologin`;
- contrasenyes bloquejades per defecte;
- grups principals validats;
- separació entre administrador, quiosc, Agent i RustDesk;
- permisos sensibles declaratius i auditables;
- escriptura atòmica i idempotent;
- rebuig de rutes insegures i enllaços simbòlics;
- estat resumit disponible per a XAAC Agent.

## Limitacions

Aquesta fase defineix i instal·la identitats i permisos base. El confinament dels processos mitjançant opcions de `systemd` es desenvolupa en la fase 9.3 i AppArmor en la fase 9.4.
