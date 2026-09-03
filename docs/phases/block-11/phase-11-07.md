# Fase 11.7 — Recuperació USB

Aquesta fase incorpora la recuperació mitjançant un dispositiu USB signat per reinstal·lar XAAC Thin Client OS quan la instal·lació local no és recuperable.

## Detecció i mitjà admés

Només s'accepten dispositius extraïbles amb l'etiqueta `XAAC_RECOVERY_USB`. El mitjà es tracta en mode només lectura amb `ro,nodev,nosuid,noexec`; qualsevol dispositiu intern, etiqueta desconeguda o estructura incompleta es rebutja.

## Confiança i versió

El manifest, la signatura i els hashes SHA-256 són obligatoris. El manifest ha d'identificar `xaac-thin-client-os`, el perfil `wyse3040`, una versió compatible i l'esquema mínim admés. Les degradacions de versió queden prohibides.

## Reinstal·lació

La imatge, el kernel i l'initramfs es verifiquen abans de l'escriptura. La reinstal·lació és transaccional, torna a verificar el resultat i conserva la identitat del dispositiu i l'enrolament. Es requereix alimentació elèctrica.

## Errors

Qualsevol error provoca un tancament segur, queda registrat de manera persistent i es comunica a XAAC Agent. Un mitjà incorrecte no pot iniciar cap escriptura.

## Configuració

```bash
xaac-os --root . configure-usb-recovery --dry-run
xaac-os --root . configure-usb-recovery
```
