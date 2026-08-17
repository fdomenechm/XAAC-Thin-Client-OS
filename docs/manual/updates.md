# Guia d’actualització

## Estat actual del Bloc 10

La Fase 10.1 defineix l’arquitectura i les comprovacions prèvies, però **encara no instal·la actualitzacions**. La instal·lació transaccional i el rollback s’implementaran en la Fase 10.2.

## Consultar l’estat

```bash
sudo xaac-update-admin status
sudo xaac-update-admin preflight
```

`preflight` comprova identitat del sistema, arquitectura, espai lliure, coherència de `dpkg`/APT i presència dels components XAAC. El keyring de releases es mostra com a requisit separat mentre encara no haja estat provisionat.

## Verificar un bundle signat

```bash
sudo xaac-update-admin check /ruta/update-manifest.json
```

La verificació és *fail-closed*: exigeix signatura OpenPGP separada, keyring autoritzat, SHA-256 correcte, metadades Debian coherents, perfil `wyse3040`, arquitectura `amd64`, conjunt complet de components i absència de downgrades.

## Instal·lació

```bash
sudo xaac-update-admin update
```

En la Fase 10.1 aquesta ordre està deliberadament deshabilitada i retorna un error informatiu. No s’ha de forçar cap instal·lació manual fora del mecanisme que s’implementarà en la Fase 10.2.
