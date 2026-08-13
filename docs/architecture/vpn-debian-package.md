# XAAC Thin Client VPN com a paquet Debian

XAAC Thin Client OS no incorpora el codi font Python de XAAC Thin Client VPN.
La revisió validada es distribueix com `packages/xaac-thin-client-vpn_0.5.1~dev0-1_all.deb`.

SHA-256: `c7288100e5e4b193716aebcf0defd12c3dbc03efdc0f7cee2bc5b9aa15c3ab82`

El `.deb` és propietari de la GUI, `xaac-vpn-manager`, D-Bus, configuració base,
traduccions i recursos. L'OS només integra el gate de sessió, afegeix
`xaac-kiosk` al grup `xaac-vpn` i habilita el manager.
