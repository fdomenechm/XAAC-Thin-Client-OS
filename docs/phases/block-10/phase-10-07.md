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

XAAC Thin Client disposa d'una configuració d'idioma pròpia i el paquet Debian parteix de `language = ca`. Per evitar que aquesta preferència interna sobreescriga la selecció de l'OS, l'instal·lador sincronitza també `/etc/xaac-thinclient/config.ini`: `ca_ES.UTF-8` correspon a `language = ca`, `es_ES.UTF-8` a `language = es` i `en_US.UTF-8` a `language = en`. La verificació final comprova `LANG`, `XKBLAYOUT` i `application.language` abans de declarar la instal·lació completada.

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

La validació en VM va demostrar que les correccions successives sobre el final de la instal·lació havien alterat un camí que ja estava funcionant abans de la Fase 10.7. Per evitar noves interferències, el final d'èxit s'ha restaurat literalment al contracte de la baseline validada.

En una instal·lació correcta la seqüència és única:

1. es completa i verifica la instal·lació;
2. es mostra el missatge de finalització;
3. l'instal·lador espera Retorn;
4. s'executa directament `systemctl poweroff`;
5. systemd realitza la parada del Live i l'apagada del terminal.

No hi ha cap helper d'apagada en aquest camí, ni neteja explícita abans de `systemctl poweroff`, ni `trap - ...`, ni `--no-block`, ni `/sbin/poweroff -f`, ni bucles d'espera. La funció `cleanup_install`, registrada com a trap des del moment en què comença el desplegament al disc, continua encarregant-se de la neteja quan el servei és aturat durant la seqüència normal de shutdown, igual que en la versió anterior a la Fase 10.7 que estava validada.

Tampoc s'aplica cap protecció nova de `tty1` al Live. `xaac-installer-welcome.service` conserva únicament el control necessari mentre està en execució (`ExecStartPre=stop getty@tty1.service` i `Conflicts=getty@tty1.service`). La política de `tty1` del sistema instal·lat, del quiosc i de Recovery és independent i no es modifica.

## Correcció: sincronització amb XAAC Thin Client

La validació posterior de la Fase 10.7 va detectar que el sistema operatiu conservava correctament el locale seleccionat, però XAAC Thin Client continuava utilitzant el valor `language = ca` inclòs per defecte en el seu paquet Debian. La correcció es fa en el mateix instal·lador, quan encara disposa de privilegis sobre el sistema de destinació, i no requereix modificar el paquet de XAAC Thin Client.

La sincronització és fail-closed: si el fitxer `/etc/xaac-thinclient/config.ini` no existeix o el valor final no coincideix amb `ca`, `es` o `en` segons la selecció, la instal·lació no es declara completada.

