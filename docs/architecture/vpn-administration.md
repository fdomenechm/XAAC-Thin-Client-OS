# Administració de XAAC Thin Client VPN

## Política administrativa

`/etc/xaac/vpn-manager.toml` és la font única de veritat per activar la VPN:

- `policy = "disabled"`
- `policy = "optional"`
- `policy = "required"`

El fitxer és de `root`, no conté secrets d'usuari i és llegit pel gate abans de
cada sessió. `xaac-vpn-manager` llig la mateixa configuració en arrancar.

Aquesta és també la frontera prevista per a XAAC Thin Client Agent: l'Agent
podrà actualitzar el fitxer de manera atòmica i reiniciar el manager, sense
introduir contrasenyes ni OTP en configuració persistent.

## DNS OpenVPN 3

XAAC Thin Client OS no usa `systemd-resolved`. El constructor inicialitza
OpenVPN 3 perquè use directament `/etc/resolv.conf`. Aquesta configuració és
necessària perquè els DNS rebuts per la VPN s'apliquen al túnel full-tunnel.

## Consoles TTY

El cursor continua ocult globalment durant l'arranc silenciós de tty1, però el
drop-in de `getty@.service` restaura explícitament el cursor a les consoles de
text autenticades.
