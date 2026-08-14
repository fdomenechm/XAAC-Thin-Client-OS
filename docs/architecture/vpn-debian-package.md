# XAAC Thin Client VPN com a paquet Debian

XAAC Thin Client OS no incorpora el codi font Python de XAAC Thin Client VPN.
La revisió validada es distribueix com `packages/xaac-thin-client-vpn_0.5.2~dev1-1_all.deb`.

SHA-256: `4392a043d73c2cff6b1c14e1c4576d1afdf07799a2d91b426b044c12a623c876`

El `.deb` és propietari de la GUI, `xaac-vpn-manager`, D-Bus, configuració base,
traduccions i recursos. L'OS només integra el gate de sessió, afegeix
`xaac-kiosk` al grup `xaac-vpn` i habilita el manager.
