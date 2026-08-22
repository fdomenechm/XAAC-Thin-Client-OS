# Fase 2.7 — Servidor SSH mínim i endurit

## Objectiu

Configurar OpenSSH dins del rootfs Debian 13 amb una política segura per defecte i preparada per a la gestió remota dels terminals XAAC.

## Configuració declarativa

`config/ssh.yaml` defineix:

- activació del servei;
- port d'escolta;
- usuaris autoritzats;
- xarxes d'origen autoritzades;
- mètodes d'autenticació;
- límits i opcions d'enduriment.

La configuració inicial només permet `xaac-admin` i admet tant contrasenya com clau pública durant la instal·lació, proves i provisionament inicial. L'accés de `root`, l'autenticació interactiva, X11, els túnels i els reenviaments queden desactivats. Després del provisionament, XAAC Management Server, mitjançant XAAC Thin Client Agent, desactiva l'autenticació per contrasenya i deixa únicament la clau pública.

## Fitxers generats

- `/etc/ssh/sshd_config.d/20-xaac-hardening.conf`
- `/etc/xaac/ssh-allowed-sources`
- enllaç d'activació de `ssh.service` dins de `multi-user.target.wants`

El fitxer `ssh-allowed-sources` és una entrada declarativa per a la fase de tallafoc. OpenSSH queda endurit des d'aquesta fase, però la restricció efectiva per adreça d'origen s'aplicarà amb nftables.

## Ús

Planificació sense modificar el rootfs:

```bash
.venv/bin/xaac-os --root . configure-ssh --dry-run
```

Execució real:

```bash
sudo .venv/bin/xaac-os --root . configure-ssh
```

Cal executar-la després de la configuració de xarxa.

## Seguretat i traçabilitat

- validació estricta de l'esquema YAML;
- validació de ports, usuaris i xarxes CIDR;
- prohibició explícita de `root`;
- autenticació inicial per contrasenya o clau pública, amb transició posterior a només clau pública;
- escriptura atòmica i permisos controlats;
- comprovació de privilegis i dels binaris/unitats d'OpenSSH;
- log en `logs/ssh-configuration.log`;
- pla i resultat incorporats al manifest;
- `config/ssh.yaml` inclòs en els hashes de fonts.
