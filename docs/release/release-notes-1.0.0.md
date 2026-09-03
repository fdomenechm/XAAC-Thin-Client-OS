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

## Correccions validades en maquinari real

- SSH actiu per defecte; durant el desplegament inicial `xaac-admin` admet contrasenya o clau pública i queda preparat perquè XAAC Management Server/Agent aplique després el mode només-clau.
- sincronització NTP automàtica amb la unitat estàndard de `systemd-timesyncd`, sense dependència circular amb `network-online.target`;
- gestió robusta d'eMMC i perfils OpenVPN 3;
- distribució de teclat de la instal·lació propagada a Wayland/labwc i menú contextual del quiosc bloquejat;
- scripts administratius `xaac-admin-change-language` i `xaac-admin-change-keyboard`, invocables directament per SSH, amb locale/`LANGUAGE` coherent i idioma/teclat independents;
- XAAC Thin Client VPN i XAAC Thin Client 1.0.0 incorporen cursor d'espera i bloqueig temporal dels controls en `Continuar`, `Omitir VPN`, `Connectar` i `Apagar`, amb restauració segura en error o cancel·lació.

## Consideracions

La release final només es considera publicada després de construir i verificar els
artefactes reals, registrar les aprovacions i generar les signatures amb la clau
privada autoritzada.
