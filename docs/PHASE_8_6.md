# Fase 8.6 — Consentiment de RustDesk

Aquesta fase incorpora el control de consentiment de les sessions de **XAAC Remote Support**.

La política predeterminada exigeix una confirmació visible de l'usuari del quiosc. La notificació mostra l'operador, el motiu i la caducitat de la sessió, i permet aprovar, denegar o cancel·lar la petició.

El mode `authorized-unattended` només és vàlid quan la petició prové de XMS, el dispositiu consta com a gestionat i una política remota autoritza expressament l'accés sense consentiment. No es permet activar aquest mode des d'una ordre local.

## Ordres

```bash
xaac-os-build configure-rustdesk-consent
xaac-os-build request-rustdesk-consent \
  --session-id SESSION \
  --source xms \
  --operator OPERADOR \
  --reason MOTIU \
  --expires-at DATA_UTC
xaac-os-build decide-rustdesk-consent \
  --session-id SESSION \
  --decision approve
```

Les decisions possibles són `approve`, `deny` i `cancel`. Totes les peticions i decisions es registren en JSON Lines. La fase 8.7 ampliarà aquest registre amb l'auditoria completa de la sessió remota.
