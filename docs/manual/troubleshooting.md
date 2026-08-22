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


## Intel SST al Dell Wyse 3040

En el Wyse 3040 (Intel Cherry Trail) poden aparéixer avisos del subsistema Intel SST/SOF durant l'arrencada encara que l'àudio funcional siga correcte. XAAC Thin Client OS **no** bloqueja ni força la desactivació d'Intel SST: el perfil d'àudio necessita conservar `snd_hdmi_lpe_audio` per a l'eixida HDMI i també admet `snd_hda_intel`.

Per a la release actual, un missatge Intel SST queda classificat com a *warning de hardware* mentre `xaac-hw-validate audio`/ALSA detecte l'eixida HDMI i no existisca una unitat d'àudio fallida. Només s'ha d'obrir una incidència de driver si desapareix l'eixida HDMI, ALSA no enumera cap dispositiu esperat o el warning va acompanyat d'una fallada funcional reproduïble. No s'han d'afegir blacklists de `snd_soc_sst*`, `snd_sof*` o `snd_hdmi_lpe_audio` com a solució preventiva.
