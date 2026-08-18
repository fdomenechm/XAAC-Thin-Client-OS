# Bloc 10 — Actualització, manteniment i recuperació

**Estat:** Fases 10.1–10.5 implementades a nivell de codi. Pendent únicament la construcció de la ISO candidata i la qualificació física final en un Dell Wyse 3040.

## Objectiu

El Bloc 10 converteix XAAC Thin Client OS en un appliance mantenible sense exigir una reinstal·lació de la ISO per cada canvi dels components XAAC. El disseny evita un esquema A/B complet per no consumir una part desproporcionada dels 8 GB d'eMMC del Wyse 3040.

El model final combina:

- actualització signada dels tres paquets XAAC com un conjunt atòmic;
- staging i preflight abans de modificar `dpkg`;
- punt de recuperació local amb paquets i configuració;
- health-check posterior i rollback automàtic;
- recuperació d'una transacció interrompuda abans d'arrancar el quiosc;
- manteniment i diagnòstic sanititzat;
- recovery local des de GRUB;
- gate pre-ISO i gate físic reproduïble.

El `factory-reset` continua intencionadament deshabilitat: només podrà activar-se quan existisca una imatge factory independent, versionada i signada. Esborrar configuració sense eixe artefacte no es considera una recuperació segura.

## Fase 10.1 — Arquitectura i versions

La política `config/update-model.yaml` defineix els components canònics:

- `xaac-thinclient`;
- `xaac-thin-client-vpn`;
- `xaac-agent`.

El manifest `xaac-update-manifest/v1` registra versió, arquitectura, perfil, canal i SHA-256. Els tres components formen un únic conjunt de compatibilitat i els downgrades accidentals queden bloquejats.

## Fase 10.2 — Transacció i rollback

`xaac-update-admin` implementa:

```sh
sudo xaac-update-admin status
sudo xaac-update-admin preflight
sudo xaac-update-admin check /ruta/update-manifest.json
sudo xaac-update-admin update /ruta/update-manifest.json --yes
sudo xaac-update-admin rollback --yes
```

La clau privada de release no forma part del projecte ni de la ISO. La clau pública es provisiona amb `scripts/provision-update-keyring.sh`. Si el keyring no existeix, la verificació queda bloquejada *fail-closed*.

La instal·lació crea el punt de recuperació abans de modificar paquets, conserva com a màxim dos punts i manté en cache root-only els `.deb` exactes necessaris per tornar a l'estat anterior. Un health-check fallit provoca rollback automàtic. `xaac-update-recover.service` recupera a l'arranc les transaccions interrompudes en estats `installing`, `validating` o `rolling_back` abans que s'inicie `greetd`.

## Fase 10.3 — Manteniment i diagnòstic

La interfície canònica és:

```sh
sudo xaac-maintenance status
sudo xaac-maintenance health
sudo xaac-maintenance network
sudo xaac-maintenance storage
sudo xaac-maintenance services
sudo xaac-maintenance logs
sudo xaac-maintenance cleanup
sudo xaac-maintenance diagnostics
```

Els bundles de diagnòstic no copien perfils NetworkManager, secrets XAAC, token d'enrolament, claus privades SSH ni cache de rollback. Els textos lliures es sanititzen abans d'entrar al bundle.

## Fase 10.4 — Recovery local

L'entrada instal·lada **XAAC Thin Client OS — Recovery** és accessible amb `Esc` durant la finestra curta de GRUB. Arranca `xaac-recovery.target`, no el quiosc, la VPN o l'Agent, i deixa la xarxa desactivada per defecte.

Des de `tty1`, després d'autenticar-se com `xaac-admin`:

```sh
sudo xaac-recovery menu
sudo xaac-recovery status
sudo xaac-recovery rollback --yes
sudo xaac-recovery repair --yes
sudo xaac-recovery repair --restore-configuration --yes
```

`repair` només és executable des del boot de recovery i repara `dpkg`, initramfs i GRUB sense executar `fsck` sobre una arrel muntada ni descarregar paquets implícitament.

## Fase 10.5 — Gate final i proves de fallada

### Gate previ a la ISO

El punt únic de validació passa a ser:

```sh
./scripts/validate-block10-release.sh
```

Aquest gate executa una única regressió completa de `pytest` —que inclou els tests dels Blocs 7, 8 i 9 i de les cinc fases del Bloc 10—, executa les comprovacions canòniques de paquet/proveniència del Bloc 7, valida la sintaxi dels gates focalitzats i comprova els tres `.deb` de producció amb `dpkg-deb`. Així s'evita repetir diverses vegades els mateixos subconjunts de tests abans d'una construcció que ja costa desenes de minuts.

`scripts/build-production-iso.sh` executa automàticament eixe gate abans d'elevar privilegis. Per tant, la construcció final és:

```sh
./scripts/build-production-iso.sh --clean
```

La fase `verify` genera, al costat de la ISO, el SHA-256 i un manifest `xaac-block10-release-manifest/v1`. El manifest indica també si el keyring públic de releases ha estat realment incorporat i deixa explícit que la validació física continua pendent.

### Matriu de fallades controlades

`./scripts/validate-block10-phase5.sh` cobreix sense modificar el host real:

- espai insuficient;
- `dpkg --audit` no net;
- esquema de manifest incorrecte;
- SHA-256 corrupte;
- error durant la instal·lació `dpkg` i rollback automàtic;
- backup de configuració corrupte;
- transacció interrompuda i rollback al següent boot;
- funcionament sense dependència de descàrregues de xarxa.

Aquestes proves són simulacions controlades en directoris temporals i amb primitives de sistema substituïdes; no instal·len paquets al host de desenvolupament.

### Gate del terminal instal·lat

La ISO instal·la:

```sh
sudo /usr/local/sbin/xaac-block10-validate
```

El validador reutilitza primer el gate complet del Bloc 9 i després comprova l'arquitectura d'actualització, el servei de recuperació d'actualitzacions, manteniment, recovery, GRUB i que `factory-reset` continue deshabilitat. No executa `update`, `rollback`, `repair` ni activa serveis; és un gate d'observació i evidència.

Per defecte deixa:

- `/var/log/xaac/block10-validation.txt`;
- `/var/log/xaac/block10-validation-evidence/`.

L'absència del keyring públic es marca com **REVIEW** i no com a `PASS`: en eixe cas el sistema és segur, però les actualitzacions externes continuen deshabilitades. Igualment, una instal·lació nova marca com **REVIEW** l'absència d'historial d'actualització/rollback fins que es realitze el cicle físic.

### Qualificació física final al Wyse 3040

La candidata no queda qualificada només perquè `pytest` i el gate de només lectura siguen verds. En el maquinari real s'ha de validar:

1. instal·lació neta de la ISO candidata;
2. `sudo /usr/local/sbin/xaac-block10-validate` sense cap `FAIL`;
3. funcionament normal de quiosc, VPN opcional i Agent;
4. accés amb `Esc` a **XAAC Thin Client OS — Recovery**, autenticació de `xaac-admin` i retorn al boot normal;
5. amb un bundle de qualificació **real, complet i signat** amb versions superiors, executar una **actualització → rollback → actualització**;
6. després de cada pas, confirmar versions, health-check i reinici;
7. provocar en laboratori un bundle rebutjat (p. ex. còpia amb SHA incorrecte) i confirmar que no es toca `dpkg`;
8. repetir `xaac-block10-validate` i conservar les evidències junt amb el manifest `.iso.release.json` i el `.sha256`.

**No es pot donar per validada físicament** la seqüència d'actualització/rollback des de l'entorn de desenvolupament ni substituir-la per una simulació. La validació física correspon al terminal Wyse real i a un bundle de release signat amb la clau de qualificació/producció autoritzada.

Quan el segon `xaac-block10-validate` no continga `FAIL`, s'hagen revisat els `REVIEW` i el cicle físic haja acabat en la nova versió funcional, el Bloc 10 es pot marcar com a tancat.
