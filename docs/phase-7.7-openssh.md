# Fase 7.7 — OpenSSH

La fase instal·la una política OpenSSH d'administració restringida. El servei queda desactivat per defecte i només pot habilitar-se temporalment mitjançant `xaac-ssh-access`, amb una duració entre 60 i 3.600 segons.

## Controls

- Només `xaac-admin` pot iniciar sessió.
- `root`, `xaac-kiosk` i `xaac-agent` estan exclosos.
- Només s'accepten claus públiques Ed25519 aprovades.
- Contrasenya, teclat interactiu, túnels i reenviaments estan desactivats.
- Les xarxes autoritzades es publiquen a `/etc/xaac/ssh-allowed-sources` perquè la fase 7.8 les aplique amb nftables.
- Les claus es gestionen a `/etc/xaac/ssh/authorized_keys/<usuari>` amb mode `0600`.
- L'activació temporal deixa estat JSON i es tanca automàticament amb un transient timer de systemd.
- Els canvis de configuració, claus i activacions queden auditats.

## Construcció

```bash
xaac-os configure-ssh --dry-run
xaac-os configure-ssh
```

## Operació al dispositiu

```bash
sudo xaac-ssh-access enable 900
sudo xaac-ssh-access status
sudo xaac-ssh-access disable
```
