# Fase 10.3 — Manteniment i diagnòstic

## Objectiu

Concentrar les operacions habituals de suport en una única CLI administrativa, sense afegir cap nou canal de gestió remota i sense exposar secrets en els paquets de diagnòstic.

La Fase 10.3 introdueix:

```bash
sudo xaac-maintenance status
sudo xaac-maintenance health
sudo xaac-maintenance network
sudo xaac-maintenance storage
sudo xaac-maintenance services
sudo xaac-maintenance logs
sudo xaac-maintenance cleanup
sudo xaac-maintenance diagnostics
```

OpenSSH continua sent l'únic mecanisme d'administració remota del terminal.

## `status`

Mostra en una única vista:

- versió de XAAC Thin Client OS i kernel;
- uptime i hora d’inici del boot actual;
- adreces IP actives;
- consum de RAM i zram;
- ocupació de l'arrel eMMC;
- versions instal·lades de `xaac-thinclient`, `xaac-thin-client-vpn` i `xaac-agent`;
- estat del Thin Client, VPN manager, Agent, NetworkManager, nftables, AppArmor i SSH;
- estat de l'última transacció d'actualització;
- últim error important del boot actual, sanititzat abans de mostrar-lo.

## `health`

Executa un health-check de manteniment independent del health-check transaccional de la 10.2. Comprova:

- llindars d'ocupació de l'arrel;
- `dpkg --audit`;
- unitats systemd fallides;
- NetworkManager, nftables i AppArmor com a serveis que han d'estar actius;
- presència de `ssh.service`, que pot romandre inactiu per política fins que l'administrador habilite temporalment l'accés;
- presència i estat dels serveis opcionals XAAC.

El resultat és `OK`, `DEGRADED` o `ERROR`. Un servei opcional absent no es converteix en una fallada crítica del terminal.

## `network`

Mostra només informació operativa de xarxa:

- dispositius i estat de NetworkManager;
- adreces IP;
- rutes IPv4 i IPv6;
- estat de NetworkManager, VPN manager i SSH.

No llig el contingut de `/etc/NetworkManager/system-connections` ni cap fitxer de credencials.

## `storage`

Mostra:

- ocupació de `/`;
- dispositius i punts de muntatge;
- model d'emmagatzematge quan està disponible;
- camps eMMC `pre_eol_info` i `life_time` publicats per sysfs;
- `smartctl -H` només si l'eina està instal·lada i el dispositiu ho suporta.

`smartmontools` no s'afegeix com a dependència obligatòria per no augmentar innecessàriament la imatge mínima del Wyse 3040.

## `services`

Resumeix `load`, `active` i `enabled` per als serveis crítics i opcionals definits per la política de la 10.3, mostra si s'ha detectat el procés real `xaac-thinclient` i enumera unitats systemd fallides.

No es torna a introduir la dependència incorrecta de `xaac-thin-client.service`: el Thin Client continua gestionat pel supervisor de la sessió quiosc.

## `logs`

Mostra un nombre acotat d'entrades `warning..alert` del boot actual i passa sempre el text per la capa de sanitització.

La sanitització elimina, entre altres, línies o valors que semblen contenir:

- contrasenyes o passphrases;
- tokens i OTP;
- capçaleres Bearer/Basic;
- secrets explícits;
- claus privades PEM;
- material `auth-user-pass`/PKCS#12;
- credencials incrustades en URL.

## `cleanup`

La neteja és deliberadament conservadora. Només:

1. elimina bundles `xaac-diagnostics-*.tar.gz` que superen la retenció definida;
2. aplica retenció temporal i de mida al journal;
3. executa `apt-get clean`.

No elimina punts de rollback, cache de paquets de rollback, configuració, claus ni staging actiu d'una actualització. La retenció dels punts de recuperació continua sent responsabilitat de la 10.2.

## `diagnostics`

Genera un únic fitxer amb format:

```text
/var/lib/xaac-maintenance/diagnostics/xaac-diagnostics-YYYYMMDD-HHMMSS.tar.gz
```

El directori té mode `0700` i el bundle mode `0600`.

Inclou informes sanitzats de:

- estat general;
- health-check;
- xarxa;
- emmagatzematge;
- serveis;
- logs;
- `dpkg --audit`;
- estat de les transaccions d'actualització;
- manifest tècnic del bundle.

No copia el contingut de configuracions sensibles. La política prohibeix explícitament incorporar, entre altres:

- `/etc/xaac/secrets`;
- `/etc/xaac-agent/enrollment.token`;
- `/etc/NetworkManager/system-connections`;
- claus privades host d'OpenSSH;
- `/var/lib/xaac-update/package-cache`.

Per tant, el bundle no conté contrasenyes, claus privades, OTP, secrets VPN ni credencials de NetworkManager per disseny. A més, qualsevol text lliure passa per sanitització abans d'entrar al `.tar.gz`.

## Administrador local

El menú de `xaac-admin` queda alineat amb la nova CLI i deixa d'usar el nom de servei obsolet `xaac-thin-client.service`. La política `sudoers` permet únicament les subordres concretes de `xaac-maintenance`, a més de les operacions administratives restringides que ja existien.

## Integració en la futura ISO

`ProductionIsoBuilder` instal·la:

```text
/etc/xaac/maintenance/policy.json
/var/lib/xaac-maintenance/state.json
/usr/local/sbin/xaac-maintenance
/usr/local/libexec/xaac_maintenance_runtime.py
/usr/lib/tmpfiles.d/xaac-maintenance.conf
```

i crea `/var/lib/xaac-maintenance/diagnostics` amb permisos root-only.

No s'habilita cap daemon, port, socket ni API remota nova.

## Gate de fase

```bash
./scripts/validate-block10-phase3.sh
```

El gate valida política, permisos, integració del constructor, menú administratiu, sanitització, retenció segura i generació controlada de bundles.

No cal generar ISO en aquesta fase. La validació física continua prevista per a la Fase 10.5, excepte si els canvis de recovery de la 10.4 obliguen a avançar una prova d'arranc.
