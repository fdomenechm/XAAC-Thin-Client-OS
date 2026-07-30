# Guia de xarxa

## Ethernet
La interfície cablejada és el transport principal. El gestor de xarxa aplica configuracions de manera transaccional i conserva un rollback.

## DHCP i IPv4 estàtica
Valideu adreça, prefix, passarel·la i DNS abans d’aplicar una configuració estàtica. Una configuració remota ha de conservar un mecanisme de retorn si es perd connectivitat.

## DNS, NTP i proxy
Configureu únicament servidors autoritzats. NTP és necessari per a certificats, signatures, actualitzacions i auditoria. Les excepcions de proxy han de ser explícites.

## VLAN i 802.1X
Les VLAN 802.1Q i IEEE 802.1X es gestionen mitjançant perfils declaratius. Protegiu certificats i credencials amb permisos restrictius i proveu renovació i recuperació.

## Diagnòstic
Comproveu enllaç, ruta, resolució DNS, sincronització horària, proxy i regles nftables abans d’atribuir una fallada al client XAAC.
