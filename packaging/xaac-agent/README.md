# XAAC Agent dins de XAAC Thin Client OS

XAAC Thin Client OS integra XAAC Agent **exclusivament** mitjançant el paquet
Debian `packages/xaac-agent_1.0.0-2_amd64.deb`.

El sistema operatiu valida abans de construir la ISO:

- capçalera i mida d'un `.deb` real;
- `Package: xaac-agent`;
- `Version: 1.0.0-2` i `Architecture: amd64`;
- dependències mínimes declarades;
- SHA-256 fixat en `config/xaac-agent-package.yaml`.

El `.deb` és l'únic propietari de `/opt/xaac-agent`, `/etc/xaac-agent`,
`/var/lib/xaac-agent`, l'usuari `xaac-agent` i les unitats systemd de l'Agent.
L'OS no recrea aquests recursos ni genera una configuració paral·lela.
