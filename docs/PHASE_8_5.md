# Fase 8.5 — Activació sota demanda de RustDesk

## Objectiu

Mantindre `rustdesk-xaac.service` desactivat fora d'una intervenció autoritzada i permetre sessions temporals iniciades localment o des de XMS.

## Política

`config/rustdesk-activation.yaml` defineix els orígens autoritzats, una duració predeterminada de 30 minuts i límits de 5 a 240 minuts. Tota sessió utilitza un token d'un sol ús; només se'n conserva el hash SHA-256. La petició efímera s'emmagatzema amb permisos `0600` i l'estat publicat per a XAAC Agent amb `0640`.

## Ordres

```bash
xaac-os configure-rustdesk-activation
xaac-os activate-rustdesk-support --source local --duration 30
xaac-os activate-rustdesk-support --source xms --duration 60 --token '<token-XMS>'
xaac-os deactivate-rustdesk-support
```

Totes admeten `--dry-run`. La infraestructura inclou un helper restringit i unitats systemd d'expiració per a tancar el servei automàticament. El consentiment de l'usuari es desenvoluparà en la fase 8.6.
