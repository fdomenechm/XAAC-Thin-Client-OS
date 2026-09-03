# Fase 10.2 — Actualització segura i rollback

## Objectiu

Convertir el contracte de la Fase 10.1 en una actualització real dels tres components XAAC mitjançant una transacció local, verificable i reversible, sense esquema A/B i sense dependre de xarxa per al rollback.

## Abast

La Fase 10.2 actualitza el conjunt complet de components:

- `xaac-thinclient`;
- `xaac-thin-client-vpn`;
- `xaac-agent`.

El `VERSION_ID` de XAAC Thin Client OS **no es modifica en aquesta fase**, perquè encara no existeix un paquet de plataforma que represente el sistema base complet. Per això el manifest instal·lable ha de correspondre exactament al `VERSION_ID` present a `/etc/os-release`. Açò evita presentar com a actualitzat un sistema base que no s'ha modificat realment.

## Flux transaccional

`sudo xaac-update-admin update MANIFEST --yes` executa:

1. preflight complet;
2. verificació OpenPGP del manifest amb `gpgv`;
3. verificació SHA-256 i de les metadades reals dels `.deb`;
4. còpia del bundle a un staging root-only;
5. nova verificació dels hashes després de copiar-lo;
6. creació del punt de recuperació;
7. comprovació que existeixen els `.deb` exactes de les versions instal·lades;
8. còpia de configuració preservable;
9. instal·lació no interactiva amb `dpkg --unpack` + `dpkg --configure`;
10. reinici únicament dels components afectats que ja estaven actius;
11. health-check fail-closed;
12. confirmació de la transacció o rollback automàtic.

Només es consideren confirmades les versions que superen el health-check.

## Primer rollback sense xarxa

El constructor de producció conserva els `.deb` exactes que porta la ISO a:

```text
/var/lib/xaac-update/package-cache/
```

amb permisos root-only. Això permet revertir també **la primera actualització** sense descarregar la versió anterior d'un repositori.

Després d'una actualització correcta, els `.deb` candidats verificats passen al mateix cache per poder usar-los com a versió anterior en operacions futures. La retenció de punts de recuperació queda limitada a dos per protegir l'eMMC de 8 GB.

## Configuració preservada

Abans de modificar paquets es crea un backup local root-only de:

- `/etc/xaac`;
- `/etc/xaac-agent`;
- `/etc/xaac-thinclient`;
- `/etc/NetworkManager/system-connections`;
- `/etc/ssh`;
- `/etc/hostname`;
- `/etc/hosts`.

Aquest backup pot contindre secrets necessaris per restaurar el terminal, per tant **no forma part de cap bundle de diagnòstic** i queda sota `/var/lib/xaac-update/recovery-points` amb accés exclusiu de root.

## Health-check real de l'appliance

La validació posterior no assumeix l'existència de `xaac-thin-client.service`, perquè XAAC Thin Client és gestionat pel supervisor de la sessió quiosc. Es comprova:

- versió exacta dels tres paquets;
- `dpkg --audit`;
- `apt-get check`;
- existència i executable dels tres binaris;
- `xaac-agent.service` només si estava actiu abans de l'actualització;
- `xaac-vpn-manager.service` només si estava actiu abans;
- reaparició del procés `xaac-thinclient` només si estava executant-se abans.

Quan canvia el Thin Client, la transacció finalitza el procés de l'usuari quiosc i deixa que el supervisor limitat existent el torne a iniciar. No es llança mai una segona instància gràfica com a root.

## Rollback automàtic i manual

Si la instal·lació o el health-check fallen, la transacció:

- reinstal·la els `.deb` anteriors del cache;
- restaura la configuració corresponent;
- valida de nou `dpkg`, APT, paquets i serveis;
- marca la combinació fallida al registre `blocked-versions.json`;
- conserva evidència de l'error.

També queda disponible:

```bash
sudo xaac-update-admin rollback --yes
```

per restaurar manualment l'últim punt de recuperació després d'una actualització que havia sigut confirmada.

## Recuperació davant una interrupció

`xaac-update-recover.service` s'executa abans del quiosc. Si l'estat persistent indica que el terminal es va apagar/reiniciar en `installing`, `validating` o `rolling_back`, intenta completar el rollback abans d'arrancar `greetd`.

Aquest servei **no usa `ProtectSystem=strict`**, perquè un rollback de paquets necessita modificar `/usr` i `/etc`. Manté altres restriccions compatibles (`NoNewPrivileges`, `ProtectHome`, `PrivateTmp`, `LockPersonality`, `RestrictRealtime`, `UMask=0077`).

## Confiança criptogràfica

No s'inventa cap clau de producció. El constructor només copia:

```text
assets/release/xaac-archive-keyring.gpg
```

si release engineering l'ha provisionat amb una clau pública real. Si no existeix, `preflight`, `check` i `update` queden bloquejats de manera segura.

Per provisionar una clau pública existent:

```bash
./scripts/provision-update-keyring.sh FINGERPRINT
```

La clau privada no entra mai al repositori ni a la ISO.

Per crear un bundle signat a la màquina de release:

```bash
XAAC_RELEASE_SIGNING_KEY=FINGERPRINT ./scripts/build-update-bundle.sh production
```

El bundle resultant conté el manifest, la signatura `.asc` i els tres `.deb`. Es pot copiar al terminal per OpenSSH/SCP i instal·lar localment. No s'introdueix cap nou mecanisme d'administració remota.

## CLI

```bash
sudo xaac-update-admin status
sudo xaac-update-admin preflight
sudo xaac-update-admin check /ruta/update-manifest.json
sudo xaac-update-admin update /ruta/update-manifest.json --yes
sudo xaac-update-admin rollback --yes
```

`update` i `rollback` exigeixen confirmació explícita amb `--yes`.

## Dependències runtime

La imatge declara explícitament `gpgv` per verificar signatures i `procps` per a `pgrep/pkill` dels health-checks i reinicis controlats de sessió.

## Gate de fase

```bash
./scripts/validate-block10-phase2.sh
```

El gate comprova política, runtime, rollback, CLI, scripts de release i integració amb el constructor, incloent simulacions de transacció correcta i de health-check fallit amb rollback automàtic.

No cal generar ISO en aquesta fase. La ISO continua ajornada fins a la Fase 10.5, llevat que la Fase 10.4 obligue a validar canvis d'arranc/recovery abans.
