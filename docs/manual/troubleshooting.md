# Guia de resolució de problemes

## El sistema no arranca
Reviseu mode UEFI, entrada GRUB, kernel, initramfs, partició EFI i journal de l’arrencada anterior. Useu el mode de diagnòstic o recuperació.

## No inicia el quiosc
Comproveu `greetd`, compositor, usuari `xaac-kiosk`, XAAC Thin Client, dependències Python i límit de reinicis del supervisor.

## Sense xarxa
Reviseu enllaç, DHCP o perfil estàtic, VLAN, 802.1X, DNS, NTP, proxy i nftables. Activeu el rollback si una configuració remota ha tallat la connexió.

## Actualització fallida
No ometeu la verificació. Reviseu staging, espai, signatura, hashes, dependències i estat transaccional. Apliqueu rollback si la validació posterior falla.

## Recuperació fallida
Verifiqueu signatura i versió del mitjà, partició de recuperació, alimentació, disc de destinació i resum JSON. Escaleu a USB o PXE només amb autorització.

## Informació per a suport
Executeu `sudo xaac-maintenance diagnostics` i adjunteu el bundle generat junt amb els passos exactes per reproduir la incidència. No copieu manualment fitxers de secrets, perfils NetworkManager, claus privades ni credencials VPN.
