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

La configuració inicial només permet `xaac-admin`, exclusivament mitjançant clau pública. L'accés de `root`, les contrasenyes, l'autenticació interactiva, X11, els túnels i els reenviaments queden desactivats.

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
- autenticació exclusiva per clau pública;
- escriptura atòmica i permisos controlats;
- comprovació de privilegis i dels binaris/unitats d'OpenSSH;
- log en `logs/ssh-configuration.log`;
- pla i resultat incorporats al manifest;
- `config/ssh.yaml` inclòs en els hashes de fonts.
