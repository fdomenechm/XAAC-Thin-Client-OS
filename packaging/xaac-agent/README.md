# XAAC Agent dins de XAAC Thin Client OS

XAAC Thin Client OS integra XAAC Agent **exclusivament** mitjançant el paquet
Debian declarat en `config/xaac-agent-package.yaml`. En el tancament del Bloc 7
la revisió esperada és `xaac-agent 1.0.0-7` per a `amd64`.

Abans de construir la ISO, el sistema valida:

- capçalera i mida d'un `.deb` real;
- `Package: xaac-agent`;
- versió i arquitectura exactes del perfil;
- dependències mínimes declarades;
- SHA-256 fixat en `config/xaac-agent-package.yaml`;
- contracte complet OS ↔ Agent del Bloc 7;
- provenança canònica `xaac-block7-release-provenance/v1`.

El `.deb` és l'únic propietari de `/opt/xaac-agent`, `/etc/xaac-agent`,
`/var/lib/xaac-agent`, l'usuari `xaac-agent` i les unitats systemd de l'Agent.
L'OS no recrea aquests recursos ni genera una configuració paral·lela.

## Bloc 7.7

Un artefacte generat amb `dpkg-deb` pot utilitzar-se únicament per a proves locals i
ha de portar `canonical=false`. La ISO de producció només accepta un paquet construït
amb `dpkg-buildpackage -us -uc -b` mitjançant el flux:

```sh
./scripts/finalize-block7-release.sh /ruta/al/xaac-agent
```

El finalitzador substitueix el paquet de prova pel `.deb` canònic, actualitza el
SHA-256 i executa els gates, les suites completes i una única construcció de la ISO.
