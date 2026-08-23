# XAAC Thin Client VPN com a paquet Debian

XAAC Thin Client OS no incorpora el codi font Python de XAAC Thin Client VPN.
La revisió validada es distribueix com `packages/xaac-thin-client-vpn_1.0.0_all.deb`.

SHA-256: `823b0d1d2cde25f73b9f90f8008bbad52cafb6461718230e81794bdd31848467`

El `.deb` és propietari de la GUI, `xaac-vpn-manager`, D-Bus, configuració base,
traduccions i recursos. L'OS només integra el gate de sessió, afegeix
`xaac-kiosk` al grup `xaac-vpn` i habilita el manager.
