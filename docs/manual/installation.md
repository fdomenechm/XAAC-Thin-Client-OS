# Guia d’instal·lació

## Abast
Instal·lació de XAAC Thin Client OS en un Dell Wyse 3040 mitjançant ISO, IMG o PXE.

## Requisits
- Dell Wyse 3040 amb UEFI i alimentació estable.
- Còpia de seguretat de qualsevol dada existent.
- Artefacte publicat amb hash SHA-256 i signatura verificats.

## ISO
1. Verifiqueu el fitxer `.sha256` i la signatura separada.
2. Graveu la ISO híbrida en un USB.
3. Arranqueu en UEFI i seleccioneu **Instal·lar XAAC Thin Client OS**.
4. Seleccioneu el disc eMMC, reviseu el resum i escriviu `INSTALL XAAC`.
5. No interrompeu el particionat, la còpia ni la instal·lació de GRUB.

## IMG
Descomprimiu la IMG XZ, verifiqueu-ne el hash i escriviu-la només sobre el dispositiu de destinació correcte. En el primer inici s’expandeix l’arrel i es regeneren els identificadors.

## PXE
Publiqueu `vmlinuz`, `initrd.img`, `rootfs.squashfs` i `boot.ipxe` en el servidor autoritzat. La instal·lació desatesa exigeix el token de confirmació configurat.

## Validació final
Comproveu UEFI, les particions `XAAC_EFI`, `XAAC_ROOT`, `XAAC_DATA` i `XAAC_RECOVERY`, l’absència de serveis crítics fallits i l’arrencada de la sessió de quiosc.
