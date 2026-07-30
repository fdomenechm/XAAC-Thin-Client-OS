# Fase 11.8 — Recuperació PXE i remota

## Objectiu

Permetre que un Dell Wyse 3040 amb la instal·lació local danyada puga iniciar una recuperació per xarxa, sempre sota una ordre XMS vàlida, verificable, d’un sol ús i confirmada localment.

## Arrencada de xarxa

La política `config/pxe-recovery.yaml` limita la recuperació a Ethernet i iPXE. El kernel, l’initramfs i la imatge de recuperació s’obtenen exclusivament mitjançant HTTPS amb validació TLS. HTTP en clar està prohibit.

## Confiança de la imatge

Abans d’escriure al dispositiu es requereixen manifest, signatura OpenPGP i hashes SHA-256. La política conserva la identitat i l’enrolament, impedeix degradacions de versió i verifica el resultat després de la restauració.

## Autorització XMS

La recuperació només pot començar amb una ordre `recovery.pxe` que incloga la identitat del dispositiu, un nonce, una antiguitat màxima de cinc minuts i semàntica d’un sol ús. Qualsevol absència o incoherència produeix una denegació *fail-closed*.

## Confirmació local

L’operador ha de confirmar físicament l’acció amb la frase exacta `RECOVER XAAC DEVICE`. La confirmació caduca i el dispositiu ha d’estar connectat a alimentació elèctrica.

## Estat i auditoria

L’estat persistent registra l’ordre, el nonce, el progrés, els errors i l’estat terminal. XAAC Agent informa XMS periòdicament i notifica finalització, fallada o cancel·lació.

## Instal·lació

```bash
xaac-os --root . configure-pxe-recovery --dry-run
xaac-os --root . configure-pxe-recovery
```

Es generen la política, l’estat inicial, l’script iPXE, el servei systemd endurit, el llançador restringit i una unitat de xarxa específica per Ethernet.

## Criteri de tancament del bloc 11

Amb aquesta fase, una instal·lació danyada pot recuperar-se localment, des d’USB o mitjançant una ordre remota de XMS i arrencada de xarxa autoritzada.
