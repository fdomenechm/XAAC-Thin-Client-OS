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

## Fase 8.2 — Transició Plymouth → quiosc → XAAC Thin Client

La Fase 8.2 elimina les carreres visuals entre l'arrancada del compositor, la
pantalla d'espera i el Thin Client:

- `tty1` es prepara amb fons blanc i cursor ocult abans que `greetd` entregue el
  control a la sessió gràfica, evitant exposar la consola negra genèrica.
- `labwc` inicia `swaybg` abans del supervisor amb el mateix actiu
  `XAAC_TC_OS.png` i fons blanc utilitzats per Plymouth. Això manté una identitat
  contínua encara que una aplicació tarde a mapar-se.
- La pantalla d'espera GTK 4 usa `gtk4-layer-shell` en Wayland i ocupa la capa
  `OVERLAY`; el Thin Client pot inicialitzar-se darrere sense aparéixer abans de
  temps.
- El supervisor espera un marcador creat quan la superfície d'espera rep el
  senyal `map`. Només després llança el client i retira la coberta visual una
  vegada complida la permanència mínima.
- Si `gtk4-layer-shell` no està disponible en un backend no Wayland, es conserva
  el `fullscreen()` GTK com a fallback. El fallback X11 pinta també el root window
  de blanc abans d'iniciar Openbox.
- El contracte local OS ↔ Agent i la porta VPN continuen sense canvis: el client
  segueix iniciant-se mitjançant `/usr/local/libexec/xaac-vpn-session-gate`.

La validació ràpida es realitza amb `scripts/validate-block8-visual.sh` i comprova
l'ordre del handoff, dependències, scripts POSIX i sintaxi Python sense construir
la ISO.

## Fase 8.3 — Errors i recuperació amb identitat XAAC

La Fase 8.3 cobreix els camins de fallada del Thin Client sense introduir accions
destructives ni modificar els contractes validats amb VPN o Agent:

- Quan el procés del Thin Client finalitza de manera inesperada, el supervisor
  conserva la política de reinici limitada i el `backoff` exponencial existent.
  Durant eixe interval mostra una superfície XAAC de recuperació en lloc de
  deixar visible només el compositor o una finestra Linux genèrica.
- La superfície de recuperació reutilitza `XAAC_TC_OS.png`, fons blanc, Roboto i
  `gtk4-layer-shell` en capa `OVERLAY`, de manera coherent amb la transició de
  la Fase 8.2.
- Cada fallada genera un codi d'incidència local de la forma
  `SES-<exit>-<intent>`. El codi facilita el suport sense mostrar journals,
  tracebacks, noms d'unitats systemd ni informació interna a l'usuari.
- Quan se supera el màxim de reinicis, el supervisor entra en estat `degraded`
  i manté una pantalla XAAC estable que indica que cal contactar amb
  l'administrador. No s'executen automàticament factory reset, rollback,
  apagada ni reinici del dispositiu.
- Si no existeix ni Wayland ni X11, `xaac-session-error` disposa d'un fallback
  mínim sobre `tty1`: neteja la consola, aplica fons blanc, oculta el cursor i
  mostra només identitat XAAC i el codi d'incidència. No inicia cap greeter ni
  login interactiu en `tty1`.
- El supervisor publica l'event local `session-recovering` abans de cada intent,
  mantenint el contracte d'estat OS ↔ Agent sense alterar-ne les rutes ni els
  permisos.

## Fase 8.4 — Apagada i reinici sense retorn visual a Debian

La Fase 8.4 cobreix el tram entre la confirmació de l'acció d'energia i el moment
en què Plymouth pren el control del framebuffer:

- Els helpers privilegiats de producció mostren primer una superfície
  `xaac-power-transition` i només després sol·liciten `systemctl poweroff` o
  `systemctl reboot`. La superfície s'executa com `xaac-kiosk`, no com root.
- El llançador descobreix el socket Wayland de la sessió a `/run/user/<uid>` i
  conserva un fallback X11. L'espera del marcador `map` és estrictament limitada:
  una fallada de GTK mai pot impedir una apagada o un reinici autoritzats.
- La superfície usa el mateix `XAAC_TC_OS.png`, fons blanc i Roboto de les fases
  anteriors, amb textos específics d'apagada o reinici i un indicador d'activitat.
  En Wayland ocupa la capa `OVERLAY` mitjançant `gtk4-layer-shell`.
- Si `systemctl` rebutja l'acció, el procés visual es tanca i el control torna al
  Thin Client, que pot informar de l'error sense deixar una pantalla de tancament
  permanent.
- Com a segon nivell de protecció, `tty1` es prepara immediatament amb fons blanc
  i cursor ocult; el servei `xaac-clear-console-before-shutdown.service` repeteix
  la neteja just abans dels serveis Plymouth d'apagada/reinici.
- No es modifica la política d'autorització: els únics executables permesos a
  `xaac-kiosk` continuen sent els helpers fixos `xaac-kiosk-poweroff` i
  `xaac-kiosk-reboot`, sense concedir sudo genèric.

## Fase 8.5 — Feedback d'activitat i fons estable de sessió

La Fase 8.5 diferencia explícitament els moments de transició dels moments en què
XAAC Thin Client ja està disponible per a l'usuari:

- El branding complet `XAAC_TC_OS.png` continua reservat a arrencada, handoff,
  recuperació i apagada/reinici.
- Mentre la superfície d'inici cobreix la pantalla, el supervisor substitueix el
  `swaybg` de branding per un fons uniforme grafit `#4a4d52`; només després retira
  l'overlay. Per tant, la sessió estable no conserva el logotip darrere del Thin
  Client i tampoc exposa un fons negre o excessivament clar.
- El fallback X11 aplica el mateix color estable mitjançant `xsetroot`.
- Les superfícies que representen treball real del sistema —inici/VPN, recuperació
  i apagada/reinici— estableixen el cursor GTK `wait`. El mode d'error estable usa
  el cursor normal i la sessió ordinària no força cap cursor d'espera.
- La sessió exporta `XCURSOR_THEME=Adwaita` i `XCURSOR_SIZE=24` abans d'iniciar
  `labwc`, garantint un cursor coherent i amb animació disponible en el tema base.

### Correcció 8.5.1 — instal·lador i handoff final

La validació física de la primera ISO 8.5 va revelar tres detalls que no podien
considerar-se tancats només amb tests estàtics:

- L'instal·lador reactiva explícitament el cursor de text en `tty1`, força
  `ca_ES.UTF-8` i aplica `setupcon`; tots els missatges de l'instal·lador eviten l'apòstrof
  tipogràfic que pot aparéixer com un glif quadrat en la consola Linux. El perfil de
  consola passa a `Uni2-Terminus16` per ampliar la cobertura Unicode.
- `labwc` configura `reuseOutputMode=yes`, evitant un canvi de mode de vídeo
  innecessari en prendre el DRM. A més, `xaac-boot-handoff.service` prepara el
  canvas blanc de `tty1` abans que Plymouth abandone la pantalla i abans de
  `greetd`.
- En Wayland, la coberta d'inici ja no desapareix després d'un temps fix: `wlrctl`
  observa `wlr-foreign-toplevel-management` i la manté amb cursor `wait` fins que
  existeix una superfície interactiva real de XAAC Thin Client o XAAC Thin Client
  VPN. El timeout continua sent limitat per evitar bloquejos permanents.

## Àrees pendents del Bloc 8

Després de la Fase 8.5 només queda la consolidació i tancament de la Fase 8.6,
incorporant la validació visual final sobre la ISO i el maquinari real.
