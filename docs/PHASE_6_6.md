# Fase 6.6 — Aplicació de polítiques

## Objectiu

Proporcionar a XAAC Agent una base transaccional i auditable per rebre, validar, preparar, aplicar, confirmar i revertir polítiques del dispositiu sense comprometre la sessió local.

## Configuració

La política del mecanisme es defineix en `config/policy-application.yaml`. El format admès és `xaac-device-policy` versió 1, amb un límit de 256 KiB i digest SHA-256 obligatori.

Les seccions inicialment admeses són:

- `client`
- `agent`
- `kiosk`
- `network`
- `devices`
- `power`

Qualsevol secció desconeguda es rebutja abans d'entrar en staging.

## Flux transaccional

1. **Recepció i validació:** es comproven esquema, identificador, revisió, seccions, mida i digest.
2. **Staging:** la política validada s'escriu atòmicament en `/var/lib/xaac-agent/policies/staging`.
3. **Aplicació:** l'anterior política activa es conserva com a rollback i la nova passa a estat `pending_confirmation`.
4. **Confirmació:** després de validar el funcionament, l'estat passa a `confirmed`.
5. **Rollback:** una fallada restaura l'última política coneguda com a vàlida i registra `rolled_back`.

L'estat transaccional queda en `/var/lib/xaac-agent/policies/state.json`.

## Ordre del constructor

```bash
xaac-os --root . configure-policy-application --dry-run
xaac-os --root . configure-policy-application
```

## Seguretat

- rutes absolutes i confinades al rootfs;
- rebuig d'enllaços simbòlics en destinacions gestionades;
- fitxers JSON escrits de manera atòmica;
- permisos restrictius;
- digest obligatori;
- llista tancada de seccions;
- rollback obligatori davant errors de validació o aplicació.

## Abast

Aquesta fase implementa el motor i el contracte local. La recepció remota des d'XMS s'integrarà amb l'enrolament i les comunicacions de gestió de fases posteriors.
