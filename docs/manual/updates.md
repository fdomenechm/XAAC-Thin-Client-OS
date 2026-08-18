# Guia d'actualització

## Estat actual del Bloc 10

Les Fases 10.1–10.5 defineixen i consoliden l'actualització transaccional dels tres components XAAC, el rollback, el manteniment, el recovery i el gate final. La instal·lació només accepta bundles complets i signats, i continua sent fail-closed si no hi ha un keyring públic de releases provisionat.

## Consultar l'estat i fer preflight

```bash
sudo xaac-update-admin status
sudo xaac-update-admin preflight
```

`preflight` comprova identitat del sistema, arquitectura, espai lliure, coherència de `dpkg`/APT i presència dels components XAAC. La verificació continua sent *fail-closed* si el keyring públic real de releases no està provisionat.

## Verificar un bundle signat

```bash
sudo xaac-update-admin check /ruta/update-manifest.json
```

S'exigeixen signatura OpenPGP separada, keyring autoritzat, SHA-256 correcte, metadades Debian coherents, perfil `wyse3040`, arquitectura `amd64`, conjunt complet de components i absència de downgrades.

## Instal·lar

```bash
sudo xaac-update-admin update /ruta/update-manifest.json --yes
```

La instal·lació crea primer un punt de recuperació, aplica els tres `.deb` com a conjunt, executa el health-check i confirma la transacció només si tot queda funcional. Si falla, intenta rollback automàtic.

## Rollback manual

```bash
sudo xaac-update-admin rollback --yes
```

Restaura l'últim punt de recuperació disponible i valida de nou paquets, configuració i serveis corresponents.

## Validació després d'una release

Després d'instal·lar una ISO candidata, executeu `sudo /usr/local/sbin/xaac-block10-validate`. Per qualificar el mecanisme d'actualització cal un bundle real signat amb versions superiors i completar físicament el cicle actualització → rollback → actualització.
