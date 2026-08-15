# XAAC Agent dins de XAAC Thin Client OS

XAAC Thin Client OS integra XAAC Agent **exclusivament** mitjançant el paquet Debian declarat en `config/xaac-agent-package.yaml`. En el tancament del Bloc 7 la revisió esperada és `xaac-agent 1.0.0-8` per a `amd64`.

Abans de construir la ISO, el sistema valida:

- capçalera i mida d'un `.deb` real;
- `Package: xaac-agent`;
- versió i arquitectura exactes del perfil;
- dependències mínimes declarades;
- SHA-256 fixat en `config/xaac-agent-package.yaml`;
- contracte complet OS ↔ Agent del Bloc 7;
- provenança canònica `xaac-block7-release-provenance/v1`.

El `.deb` és l'únic propietari de `/opt/xaac-agent`, `/etc/xaac-agent`, `/var/lib/xaac-agent`, l'usuari `xaac-agent` i les unitats systemd de l'Agent. L'OS no recrea aquests recursos ni genera una configuració paral·lela.

## Bloc 7.7

XAAC Agent i XAAC Thin Client OS es construeixen de manera independent. El projecte OS **no necessita ni rep la ruta del codi font de l'Agent**.

Una vegada construït canònicament l'Agent, s'incorpora el paquet amb:

```sh
./scripts/import-xaac-agent-package.sh /ruta/al/xaac-agent_1.0.0-8_amd64.deb
```

El fitxer `xaac-agent_1.0.0-8_amd64.deb.provenance.json` ha d'estar al costat del `.deb`. L'importador valida ambdós artefactes, actualitza automàticament el perfil i executa els gates de Bloc 7.

Després, el flux habitual de l'OS és:

```sh
./scripts/build-production-iso.sh --clean
```

Un artefacte generat amb `dpkg-deb` pot utilitzar-se únicament per a proves locals i ha de portar `canonical=false`; la ISO de producció el rebutja.
