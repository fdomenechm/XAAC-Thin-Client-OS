# Bloc 8 — Acabat visual i experiència d'appliance

Aquest document descriu el bloc de consolidació visual posterior a les integracions
validades de XAAC Thin Client, XAAC Thin Client VPN i XAAC Thin Client Agent.

> `docs/phases/block-08/` pertany a l'històric del calendari original i conserva
> les antigues fases de RustDesk. El present Bloc 8 és el bloc de consolidació del
> producte actual i no reobre ni modifica aquella integració històrica.

## Objectiu

El terminal instal·lat ha de presentar-se com un appliance XAAC des de l'encesa
fins a l'apagat. Durant el flux normal no han d'aparéixer menús Debian/GRUB,
missatges de systemd, cursor de consola, greeters interactius ni transicions que
exposen una sessió Linux genèrica.

La consola administrativa autenticada continua disponible a les TTY autoritzades
i els modes de diagnòstic continuen existint, però sempre sota una acció explícita
de l'administrador.

## Fase 8.1 — Cadena d'arrencada XAAC

La Fase 8.1 consolida el camí d'arrencada sense generar encara una nova capa de
lògica sobre Thin Client, VPN o Agent:

- `config/uefi.yaml` és la font de la política visual/silenciosa del kernel.
- Els paràmetres específics del maquinari i els visuals es fusionen sense opcions
  contradictòries; per exemple, `loglevel=0` substitueix l'antic `loglevel=3` del
  perfil comú en la línia final de boot.
- La ISO Live i el sistema instal·lat utilitzen la mateixa política de kernel.
- El menú GRUB de la ISO queda ocult en l'arrencada normal amb una finestra curta
  de dos segons. `Esc` permet mostrar el menú i seleccionar el diagnòstic de només
  lectura.
- El GRUB del sistema instal·lat continua ocult (`timeout=0`) i la seua entrada
  XAAC rep també els paràmetres de maquinari del perfil actiu.
- Plymouth continua usant `XAAC_TC_OS.png` en arrencada, reinici i apagat.
- La fase `boot` comprova que descriptor, script i imatge del tema XAAC han quedat
  realment inclosos en l'`initramfs`; si no hi són, la construcció falla abans de
  crear la ISO.

## Àrees pendents del Bloc 8

Les iteracions següents revisaran la transició Plymouth → compositor → pantalla
d'inici → XAAC Thin Client, el comportament de login/quiosc, les pantalles d'error
i recuperació, les transicions de reinici/apagat i una validació final sobre
maquinari real. Es prioritzaran canvis que es puguen validar sense reconstruir la
ISO i es reservarà la generació completa per a punts de control útils.
