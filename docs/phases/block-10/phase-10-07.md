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


## Correcció diagnosticada del Live Installer (20-08-2026)

La depuració de la ISO real amb `systemd.debug_shell=1` i una traça del pas 9 va permetre identificar la causa exacta de la terminació abans del prompt final. L'ordre que fallava era:

```sh
cp "$mount_root/etc/locale.conf" "$mount_root/etc/default/locale"
```

En Debian 13 els dos camins poden resoldre al mateix fitxer. En eixe cas `cp` retorna un estat no-zero amb el missatge «són el mateix fitxer» i, com l'instal·lador usa `set -e`, el procés acabava abans de `xaac_say complete`. La persistència del locale escriu ara directament els dos camins amb `printf`; la mateixa operació és vàlida tant si són fitxers independents com si `/etc/default/locale` és un enllaç a `/etc/locale.conf`.

La mateixa sessió de depuració va demostrar dos defectes addicionals de reinstal·lació/neteja:

- `wipefs -a` podia rebutjar una taula de particions existent; s'utilitza ara `wipefs --all --force` abans de recrear la GPT.
- Els muntatges de `/mnt/xaac-target` es propagaven a namespaces de serveis del Live (`systemd-udevd`, `systemd-logind`, NetworkManager, XAAC VPN i XAAC Agent). Això podia deixar `/dev/sda2` «in use» en una nova execució encara que ja no apareguera muntada en la shell de depuració.

Per evitar aquesta propagació, `xaac-installer-welcome.service` usa:

```ini
PrivateMounts=yes
```

Els `rbind` de `/dev`, `/sys` i `/run` continuen marcant-se `rslave` dins del namespace privat. `cleanup_install` usa desmuntatge recursiu i el handler `xaac_installer_exit` és l'únic `trap EXIT`: una fallada neteja el target i manté el missatge controlat en `tty1`, en lloc de substituir el handler d'error per un trap de neteja independent.

En una instal·lació correcta el contracte continua sent:

1. es completa i verifica la instal·lació;
2. es mostra el missatge de finalització;
3. es mostra `Premeu Retorn per apagar el sistema:` (o la traducció seleccionada) i s'espera l'entrada;
4. després de Retorn `xaac_request_poweroff` desarma els traps i invoca `systemctl poweroff`;
5. el procés roman viu fins que systemd completa l'apagada.

El final del script continua sent deliberadament:

```sh
xaac_say complete
xaac_prompt poweroff
IFS= read -r _answer
xaac_request_poweroff
```

`xaac-installer-welcome.service` manté `Conflicts=getty@tty1.service` i no usa `OnFailure` ni cap servei `restore-getty`. En cas d'error, el propi instal·lador conserva la consola, informa de la fallada i demana Retorn per reiniciar.

Els tests mantenen un SHA-256 del script Live complet després d'aquesta correcció diagnosticada. Qualsevol canvi futur del Live Installer ha de ser explícit i actualitzar alhora les regressions funcionals.

## Sincronització de llengua de XAAC Thin Client fora del Live Installer

La selecció de llengua del sistema continua sense modificar `application.language` durant la instal·lació. El helper `/usr/local/sbin/xaac-sync-thinclient-language`, executat per `xaac-thinclient-language-sync.service`, aplica `ca_ES.UTF-8 → ca`, `es_ES.UTF-8 → es` o `en_US.UTF-8 → en` abans de `greetd` en el sistema ja instal·lat.

La unitat incorpora `ConditionKernelCommandLine=!xaac.mode=installer`, de manera que aquesta sincronització no participa en cap moment en el Live Installer ni en el seu flux de finalització.
