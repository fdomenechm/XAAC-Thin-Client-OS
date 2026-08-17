# Fase 6.7 — Inventari

Aquesta fase incorpora un inventari local, determinista i auditable perquè XAAC Agent puga comunicar a XMS l'estat efectiu del terminal.

## Contingut

L'informe `xaac-device-inventory` v1 inclou:



## Ordres

```bash
xaac-os --root . collect-device-inventory --dry-run
xaac-os --root . collect-device-inventory
```

Els resultats es guarden en `/var/lib/xaac-agent/inventory/` i el manifest del format en `/etc/xaac/device-inventory-manifest.json`.

La fase no envia informació a cap servidor. L'enviament autenticat correspon a la fase 6.8 d'enrolament XMS.
