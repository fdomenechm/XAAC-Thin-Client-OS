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

El resum de `/recovery/installer/installation-summary.txt` registra la configuració que pertany al Live Installer:

```text
locale=<locale seleccionat>
keyboard_layout=<layout seleccionat>
```

La llengua pròpia de XAAC Thin Client no es valida ni s'escriu en aquest resum perquè la sincronització es produeix posteriorment, en el sistema ja instal·lat.

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


## Correcció definitiva del control de `tty1` i apagada

Després de diverses regressions en VM, el control del Live Installer queda congelat sobre la implementació de `20260819-175805`, que va ser validada amb instal·lació completa correcta. Tant el script `/usr/local/sbin/xaac-installer-welcome` com la unitat `xaac-installer-welcome.service` es mantenen amb el mateix flux funcional.

En una instal·lació correcta la seqüència és:

1. es completa i verifica la instal·lació;
2. es fa `sync`;
3. es mostra el missatge de finalització;
4. es mostra `Premeu Retorn per apagar el sistema:` i el procés queda bloquejat esperant l'entrada;
5. després de Retorn s'invoca `xaac_request_poweroff`;
6. el helper sol·licita `systemctl poweroff` i manté viu el procés fins que systemd executa l'apagada.

El final del script és, deliberadament:

```sh
xaac_say complete
xaac_prompt poweroff
IFS= read -r _answer
xaac_request_poweroff
```

`xaac-installer-welcome.service` conserva `Conflicts=getty@tty1.service` i atura `getty@tty1` abans d'arrancar l'instal·lador. **No usa `OnFailure` i no existeix cap `xaac-installer-restore-getty.service`**. Això evita que una incidència del Live Installer expose un prompt de login en `tty1`.

El mateix script manté un `trap EXIT` propi. Si alguna ordre retorna error, l'instal·lador conserva la consola, mostra un missatge d'error i demana Retorn per reiniciar; no allibera `tty1` a un `getty`.

Per evitar una nova regressió accidental, els tests bloquegen també el SHA-256 del script Live generat:

```text
2692fad417fea4941e7ae4f71f8d511ee158e31f30792972029cab087b2d7649
```

Aquest hash correspon al Live Installer validat de `20260819-175805`. Qualsevol canvi futur en el script haurà de ser explícit i actualitzar la prova de regressió.

## Sincronització de llengua de XAAC Thin Client fora del Live Installer

La selecció de llengua del sistema continua sense modificar `application.language` durant la instal·lació. El helper `/usr/local/sbin/xaac-sync-thinclient-language`, executat per `xaac-thinclient-language-sync.service`, aplica `ca_ES.UTF-8 → ca`, `es_ES.UTF-8 → es` o `en_US.UTF-8 → en` abans de `greetd` en el sistema ja instal·lat.

La unitat incorpora `ConditionKernelCommandLine=!xaac.mode=installer`, de manera que aquesta sincronització no participa en cap moment en el Live Installer ni en el seu flux de finalització.
