# Fase 9.7 — Signatura de paquets

Aquesta fase estableix la confiança criptogràfica del repositori APT de XAAC i dels paquets distribuïts fora de línia.

## Controls

- El repositori XAAC utilitza exclusivament HTTPS i una clau indicada amb `Signed-By`.
- APT rebutja repositoris insegurs, degradacions a connexions no autenticades i paquets sense autenticar.
- La política diferencia la clau activa, les claus anteriors encara confiables i les claus revocades.
- Una mateixa empremta no pot aparéixer simultàniament com a confiable i revocada.
- Els paquets offline requereixen un manifest SHA-256 i una signatura separada validada amb `gpgv`.
- La política i l'estat efectiu es publiquen per a auditoria de XAAC Agent.

## Rotació

Abans de substituir la clau activa, la clau nova s'ha de distribuir en el keyring de confiança. Durant la finestra de transició, l'antiga passa a `trusted_previous`. Finalitzada la migració, s'elimina de les claus confiables o s'incorpora a `revoked` si hi ha compromís.

## Ordre

```bash
xaac-os --root . configure-package-signing --dry-run
xaac-os --root . configure-package-signing
```

Les claus públiques i el keyring binari són artefactes de publicació. Les claus privades no formen part del repositori ni del ZIP consolidat.
