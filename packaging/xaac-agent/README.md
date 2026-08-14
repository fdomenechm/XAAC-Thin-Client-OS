# XAAC Agent dins de XAAC Thin Client OS

XAAC Thin Client OS integra XAAC Agent **exclusivament** mitjançant el paquet
Debian `packages/xaac-agent_1.0.0-4_amd64.deb`.

El sistema operatiu valida abans de construir la ISO:

- capçalera i mida d'un `.deb` real;
- `Package: xaac-agent`;
- `Version: 1.0.0-4` i `Architecture: amd64`;
- dependències mínimes declarades;
- SHA-256 fixat en `config/xaac-agent-package.yaml`.

El `.deb` és l'únic propietari de `/opt/xaac-agent`, `/etc/xaac-agent`,
`/var/lib/xaac-agent`, l'usuari `xaac-agent` i les unitats systemd de l'Agent.
L'OS no recrea aquests recursos ni genera una configuració paral·lela.

## Bloc 7.4

La revisió `1.0.0-4` incorpora la política VPN remota tipada. El helper del paquet
només pot invocar `/usr/local/sbin/xaac-vpn-admin` per a `status --json` o
`policy disabled|optional|required`. L'OS proporciona aquest executable i valida que
l'Agent conserve `ReadWritePaths=/etc/xaac` com a única excepció necessària sota
`ProtectSystem=strict`.
