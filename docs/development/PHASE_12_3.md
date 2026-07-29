# Fase 12.3 — Paquet PXE

La fase incorpora un constructor declaratiu del paquet PXE de producció per al Dell Wyse 3040.

## Components

- `vmlinuz` i `initrd.img` per a l'arrencada en xarxa.
- `rootfs.squashfs` com a sistema arrel immutable.
- `boot.ipxe` amb arguments d'arrencada controlats.
- `config/unattended.json` per a la instal·lació desatesa.
- manifest estable i fitxer de hashes SHA-256.

## Seguretat

La instal·lació desatesa exigeix un token de confirmació, limita el perfil a `wyse3040` i declara explícitament l'esborrat del disc de destinació. La preparació rebutja rutes absolutes, components `..` i destinacions que siguen enllaços simbòlics.

## Ús

```bash
xaac-os build-pxe --dry-run
xaac-os build-pxe
.build/pxe/build-pxe.sh
```

La preparació no necessita privilegis. El guió final només copia artefactes ja construïts i genera els hashes del bundle.
