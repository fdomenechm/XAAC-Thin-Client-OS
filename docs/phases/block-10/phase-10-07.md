# Fase 10.7 — Selecció d'idioma i teclat durant la instal·lació

La Fase 10.7 elimina l'assumpció que totes les instal·lacions han d'utilitzar català/valencià. El rootfs Live conserva `ca_ES.UTF-8` i teclat espanyol com a valors inicials segurs, però l'instal·lador demana explícitament la llengua i la distribució física del teclat abans de seleccionar cap disc.

## Llengües disponibles

L'instal·lador ofereix tres opcions:

- **Valencià / Català** → `ca_ES.UTF-8`;
- **Español** → `es_ES.UTF-8`;
- **English** → `en_US.UTF-8`.

La selecció canvia immediatament `LANG` i `LC_ALL` de la sessió d'instal·lació. A partir d'eixe punt, els prompts, advertiments, errors, fases de progrés i missatge final es mostren en la llengua triada.

Els tres locales continuen generats al rootfs, de manera que no és necessària xarxa ni instal·lar paquets addicionals durant el procés.

## Teclat

La distribució del teclat es tria independentment de la llengua:

- **Espanyol (`es`)**, opció predeterminada;
- **English (US) (`us`)**.

L'instal·lador aplica el keymap seleccionat a la consola Live amb `loadkeys` quan està disponible. La separació evita associar incorrectament una interfície en anglès amb un teclat físic US, o una interfície en català/espanyol amb un teclat diferent.

## Persistència al sistema instal·lat

Durant la consolidació s'escriuen els valors seleccionats en:

```text
/etc/locale.conf
/etc/default/locale
/etc/default/keyboard
```

`/etc/locale.conf` és el fitxer principal de locale utilitzat per Debian 13; `/etc/default/locale` es conserva també per compatibilitat amb components que encara el consulten. El teclat es persisteix directament en `/etc/default/keyboard`. No es reexecuten `update-locale` ni `dpkg-reconfigure keyboard-configuration` dins del chroot de destinació, perquè els locales ja estan generats en la imatge i la configuració persistent pot aplicar-se directament.

XAAC Thin Client disposa d'una configuració d'idioma pròpia i el paquet Debian parteix de `language = ca`. Aquesta configuració **no es modifica ni es verifica dins del Live Installer**. El Live només persisteix el locale seleccionat; en el primer arrencament del sistema instal·lat, `xaac-thinclient-language-sync.service` s'executa abans de `greetd` i transforma `ca_ES.UTF-8 → ca`, `es_ES.UTF-8 → es` i `en_US.UTF-8 → en`. Així, una incidència en la configuració de l'aplicació no pot impedir que l'instal·lador arribe al missatge final i a l'apagada.

El resum de `/recovery/installer/installation-summary.txt` registra, a més:

```text
locale=<locale seleccionat>
keyboard_layout=<layout seleccionat>
thinclient_language=<ca|es|en>
```

## Zona horària

La Fase 10.7 **no converteix l'instal·lador en un instal·lador Debian genèric**. La zona horària continua fixada a:

```text
Europe/Madrid
```

## Validació

Gate focalitzat:

```sh
./scripts/validate-block10-phase7.sh
```

Aquesta fase és prèvia a la qualificació sobre el Dell Wyse 3040. La primera instal·lació física del Bloc 11 validarà també el canvi real de llengua i teclat.


## Correcció de finalització de l'instal·lador

La validació en VM va demostrar que les proteccions addicionals introduïdes al Live per evitar un `getty` intermedi havien complicat el camí d'apagada fins al punt que, després de prémer Retorn, el terminal podia quedar encés. El contracte correcte és deliberadament més simple i coincideix amb el comportament que ja havia funcionat abans de la Fase 10.7.

En una instal·lació correcta la seqüència és única i recupera literalment el control de finalització de la baseline anterior a la Fase 10.7:

1. es completa i verifica la instal·lació;
2. es fa `sync`;
3. es mostra el missatge de finalització;
4. l'instal·lador mostra `Premeu Retorn per apagar el sistema:` i queda bloquejat en el `read`;
5. només després de rebre Retorn s'executa directament `systemctl poweroff`.

Entre el `read` final i `systemctl poweroff` **no hi ha cap helper, cleanup explícit, desarmat de traps, fallback, `--no-block`, mask de `tty1` ni bucle d'espera**. La neteja dels muntatges continua sent responsabilitat del `trap cleanup_install` original quan systemd para l'instal·lador durant l'apagada.

`xaac-installer-welcome.service` recupera també la topologia original validada: atura i entra en conflicte amb `getty@tty1.service` mentre està actiu i usa `OnFailure=xaac-installer-restore-getty.service` únicament si l'instal·lador acaba amb error. La política de `tty1` del sistema **instal·lat** (quiosc i Recovery) no es modifica.

## Correcció definitiva: sincronització amb XAAC Thin Client fora del Live Installer

La regressió es va identificar en la verificació final introduïda per sincronitzar `application.language`. En instal·lacions en castellà o anglès, el paquet desplegat encara contenia `language = ca` en eixe punt; la comprovació `grep ... $install_language` retornava error, `set -e` terminava l'instal·lador **abans** del missatge final i `OnFailure` restaurava `tty1`. Açò produïa exactament el símptoma observat: pantalla netejada i prompt de login del sistema Live en lloc de `Premeu Retorn per apagar`.

La correcció elimina del Live Installer tant l'escriptura com la verificació de `application.language`. El flux d'èxit conserva literalment:

```sh
xaac_say complete
xaac_prompt poweroff
IFS= read -r _answer
systemctl poweroff
```

La sincronització es trasllada a `/usr/local/sbin/xaac-sync-thinclient-language`, activat per `xaac-thinclient-language-sync.service` amb `ConditionKernelCommandLine=!xaac.mode=installer` i `Before=greetd.service`. Per tant, només s'executa sobre el sistema ja instal·lat.
