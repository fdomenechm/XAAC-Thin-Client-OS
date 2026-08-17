# Notes de la versió 1.0.0

XAAC Thin Client OS 1.0.0 completa el primer cicle estable del projecte. Inclou el
constructor Debian 13, suport específic per al Dell Wyse 3040, sessió segura de
quiosc, experiència visual d'appliance de punta a punta, gestió mitjançant XAAC Agent,
administració remota restringida mitjançant OpenSSH, hardening, actualització, recuperació i constructors de producció.

## Abast funcional

- instal·lació ISO, IMG i PXE;
- clonació i primer inici amb regeneració d'identitat;
- xarxa corporativa, VLAN i IEEE 802.1X;
- actualització signada, anells de desplegament i rollback;
- recuperació local, partició, factory reset, USB i PXE;
- packaging Debian i repositoris de producció;
- validació automatitzada i proves finals de maquinari.
- experiència d'appliance XAAC validada en maquinari real, amb arrencada/transicions pròpies, canvas granit i feedback visual d'activitat;

## Consideracions

La release final només es considera publicada després de construir i verificar els
artefactes reals, registrar les aprovacions i generar les signatures amb la clau
privada autoritzada.
