# Fase 9.4 — AppArmor

Aquesta fase incorpora confinament Mandatory Access Control per als processos principals de XAAC Thin Client OS.

## Política

`config/apparmor.yaml` defineix perfils per a XAAC Agent, XAAC Thin Client i XAAC Remote Support. Cada perfil declara executable, abstraccions, rutes de lectura i escriptura, xarxa, capabilities, senyals i mode d'aplicació.

XAAC Agent i XAAC Thin Client s'instal·len en mode `enforce`. RustDesk queda inicialment en mode `complain` per permetre l'ajust amb evidència de sessions reals abans de passar-lo a `enforce`.

## Aplicació

```bash
xaac-os --root . configure-apparmor --dry-run
xaac-os --root . configure-apparmor
```

Els perfils es generen en `/etc/apparmor.d`, els perfils en observació s'enllacen des de `force-complain`, i la política i l'estat auditable es publiquen per a XAAC Agent.

## Validació en imatge real

Després de construir la imatge cal executar `apparmor_parser -r` sobre els perfils, comprovar `aa-status` i revisar denegacions amb `journalctl -k | grep apparmor`. Les denegacions s'han d'analitzar i convertir en regles mínimes; no s'han de substituir per permisos amplis.
