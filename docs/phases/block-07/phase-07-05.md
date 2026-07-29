# Fase 7.5 — IEEE 802.1X

La fase incorpora autenticació IEEE 802.1X cablejada amb `wpa_supplicant`, mètodes EAP-TLS i PEAP/MSCHAPv2, certificats sota `/etc/xaac/certificates`, credencials separades amb permisos `0600`, estat consumible per XAAC Agent, diagnòstic sense secrets, renovació de certificats i rollback transaccional.

## Ordre

```bash
xaac-os configure-ieee8021x --eap tls --identity dispositiu@example.org \
  --ca-certificate /etc/xaac/certificates/ca.pem \
  --client-certificate /etc/xaac/certificates/client.pem \
  --private-key /etc/xaac/certificates/client.key
```

La configuració PEAP requereix `--password`. Tots dos modes admeten `--source remote`, `--rollback` i `--dry-run`.
