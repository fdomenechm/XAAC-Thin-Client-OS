# Fase 6.3 — Identitat del dispositiu

## Objectiu

Dotar cada instal·lació de XAAC Thin Client OS d'una identitat única, persistent i verificable per XAAC Agent i, posteriorment, XMS.

## Implementació

- UUID v4 propi del dispositiu, generat una sola vegada.
- lectura segura del número de sèrie DMI;
- selecció determinista d'una adreça MAC unicast;
- hostname `xaac-<prefix UUID>`;
- persistència en `/var/lib/xaac-agent/identity/device.json`;
- certificat X.509 autosignat RSA-3072 amb UUID com a CN i URI SAN;
- clau privada amb mode `0600` i certificat amb mode `0644`;
- inicialització coherent de `/etc/hostname` i `/etc/machine-id`;
- detecció d'enllaços simbòlics i de material persistent incomplet;
- operació idempotent: una identitat existent vàlida no es regenera.

## Ordre

```bash
xaac-os --root . configure-device-identity
```

Planificació sense escriptures:

```bash
xaac-os --root . configure-device-identity --dry-run
```

## Limitacions

El certificat inicial és autosignat. L'enrolament de la fase 6.8 el substituirà o vincularà amb la identitat emesa per XMS.
