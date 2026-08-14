# XAAC Thin Client VPN com a paquet Debian

XAAC Thin Client OS no incorpora el codi font Python de XAAC Thin Client VPN.
La revisió validada es distribueix com `packages/xaac-thin-client-vpn_0.5.2~dev0-1_all.deb`.

SHA-256: `e6ef0d41d5d12ad4b40f8cd467c66b632c882072b00b83627419bb989ad1d3b0`

El `.deb` és propietari de la GUI, `xaac-vpn-manager`, D-Bus, configuració base,
traduccions i recursos. L'OS només integra el gate de sessió, afegeix
`xaac-kiosk` al grup `xaac-vpn` i habilita el manager.
