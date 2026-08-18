# Guia d'actualització

## Estat actual del Bloc 10

Les Fases 10.1–10.6 defineixen i consoliden l'actualització transaccional dels tres components XAAC, el rollback, el manteniment, el recovery i el gate final. La instal·lació només accepta bundles complets i signats, i continua sent fail-closed si no hi ha un keyring públic de releases provisionat.

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


## Actualitzar el sistema base Debian 13 (Fase 10.6)

No utilitzeu `sudo apt update && sudo apt upgrade` com a procediment administratiu ordinari. La via suportada és:

```bash
sudo xaac-update-admin os-status
sudo xaac-update-admin os-check
sudo xaac-update-admin os-update --yes
```

`os-check` només s'admet en l'arranc normal (no dins del mode Recovery) i valida que el terminal continue sobre Debian 13/trixie, que les úniques fonts APT siguen `trixie`, `trixie-updates` i `trixie-security`, que totes estiguen lligades al keyring oficial de Debian, que `dpkg` siga coherent i que hi haja espai suficient. Després actualitza els índexs i simula `apt-get upgrade --with-new-pkgs --no-remove`.

`os-update` descarrega primer el conjunt complet, reverifica el mateix pla i instal·la amb `--no-download`. Queden bloquejats els downgrades, les eliminacions, els canvis dels tres paquets XAAC i qualsevol canvi de release major. `dist-upgrade` i `full-upgrade` no formen part del runtime.

El sistema no reinicia automàticament. Si `reboot_required` és cert, reinicieu en una finestra de manteniment. Si l'estat passa a `failed_requires_recovery`, arranqueu l'entrada Recovery i executeu `sudo xaac-recovery status` seguit de `sudo xaac-recovery repair --yes`.
