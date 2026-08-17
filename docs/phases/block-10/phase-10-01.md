# Fase 10.1 — Arquitectura d'actualització i política de versions

## Objectiu

Definir i integrar el contracte segur d'actualització de XAAC Thin Client OS sense instal·lar encara cap actualització. Aquesta fase fixa versions, compatibilitat, manifest, verificació criptogràfica, preflight i superfície administrativa.

## Decisions arquitectòniques

- No s'utilitza un esquema A/B complet, perquè el Dell Wyse 3040 disposa només de 8 GB d'eMMC.
- Els components XAAC actualitzables són paquets Debian reals: `xaac-thinclient`, `xaac-thin-client-vpn` i `xaac-agent`.
- La versió de la plataforma XAAC Thin Client OS es llig des de `/etc/os-release` (`VERSION_ID`).
- Les versions del sistema segueixen SemVer; les versions dels paquets es comparen amb la semàntica de versions Debian.
- Els downgrades queden prohibits per defecte.
- Els tres components XAAC formen un conjunt de compatibilitat complet: un manifest de release ha de declarar les tres versions, encara que una futura transacció puga ometre la reinstal·lació d'un paquet que no haja canviat.
- L'actualització de la plataforma es modela com un conjunt controlat de paquets Debian; no es crea una segona partició arrel.

## Manifest de release

L'ordre del constructor:

```bash
xaac-os --root . create-update-manifest
```

genera per defecte un manifest per al canal corresponent al `config/build.yaml` (`development` → `laboratory`):

```text
.build/artifacts/xaac-update-manifest.json
```

El manifest `xaac-update-manifest/v1` conté:

- versió objectiu de XAAC Thin Client OS;
- canal (`laboratory`, `pilot` o `production`), derivat del canal de build quan no s'indica explícitament;
- perfil `wyse3040` i arquitectura `amd64`;
- versió mínima de sistema compatible;
- nom, versió Debian, arquitectura, mida i SHA-256 de cada `.deb`;
- SHA-256 intern del payload del manifest;
- exigència de signatura OpenPGP separada i keyring de confiança.

La generació és determinista: els mateixos artefactes i versions produeixen el mateix manifest.

## Verificació criptogràfica

Els bundles externs han d'estar signats amb una signatura OpenPGP separada (`.asc`). La verificació usa `gpgv` i el keyring:

```text
/usr/share/keyrings/xaac-archive-keyring.gpg
```

No s'inclou cap clau privada al codi font ni es genera cap clau fictícia. Mentre el keyring real de releases no siga provisionat, la verificació de bundles falla de manera segura (*fail-closed*). El provisionament del canal real d'actualització forma part de la fase 10.2.

## Preflight

`xaac-update-admin preflight` comprova, sense modificar el sistema:

- identitat `xaac-thin-client-os`;
- arquitectura Debian `amd64`;
- almenys 512 MiB lliures a `/var`;
- `dpkg --audit` net;
- `apt-get check` sense bloqueig d'escriptura;
- presència dels tres components XAAC crítics;
- presència del keyring de releases, reportada separadament perquè en 10.1 encara pot no estar provisionat.

La política també declara quina configuració haurà de preservar la transacció de la fase 10.2 (`/etc/xaac`, `/etc/xaac-agent`, NetworkManager, SSH, hostname i hosts).

## CLI administrativa instal·lada

La futura ISO incorpora:

```bash
sudo xaac-update-admin status
sudo xaac-update-admin preflight
sudo xaac-update-admin check MANIFEST.json
```

`check` exigeix root perquè, després d'una verificació satisfactòria, registra l'estat i l'auditoria. Abans de confiar en el contingut JSON verifica la signatura OpenPGP; després valida SHA-256, metadades reals dels `.deb`, arquitectura, perfil, compatibilitat i absència de downgrades.

L'ordre següent existeix només per deixar estable la superfície CLI:

```bash
sudo xaac-update-admin update
```

En la fase 10.1 retorna explícitament que la instal·lació està deshabilitada. La transacció real i el rollback corresponen a la fase 10.2.

## Integració amb la ISO de producció

`ProductionIsoBuilder.phase_configure()` ja instal·la al rootfs:

- `/etc/xaac/update/policy.json` (`0640`);
- `/var/lib/xaac-update/state.json` (`0640`);
- `/usr/share/xaac/update/current-release.json`;
- `/usr/local/sbin/xaac-update-admin` (`0750`).

No cal generar una ISO per validar aquesta fase.

## Gate de fase

```bash
./scripts/validate-block10-phase1.sh
```

El gate comprova model, manifests, CLI administrativa i integració amb el constructor de producció, i genera temporalment un manifest real a partir dels tres `.deb` inclosos al repositori.
