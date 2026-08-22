# XAAC Thin Client VPN com a paquet Debian

XAAC Thin Client OS no incorpora el codi font Python de XAAC Thin Client VPN.
La revisió validada es distribueix com `packages/xaac-thin-client-vpn_1.0.0_all.deb`.

SHA-256: `d896b13b0a3c01c3cca07aeaf92e3ebe67a946903d0121d18147d3e762963908`

El `.deb` és propietari de la GUI, `xaac-vpn-manager`, D-Bus, configuració base,
traduccions i recursos. L'OS només integra el gate de sessió, afegeix
`xaac-kiosk` al grup `xaac-vpn` i habilita el manager.
