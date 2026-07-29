# Constructor de la imatge

Aquest directori forma part de l'estructura obligatòria de XAAC Thin Client OS i agrupa els recursos auxiliars del constructor d'imatges.

Els subdirectoris es conserven versionats encara que temporalment no continguen implementacions:

- `auto/`: configuració automatitzada del constructor.
- `hooks/`: punts d'extensió específics del procés de construcció.
- `scripts/`: scripts interns del constructor.
- `templates/`: plantilles utilitzades per generar artefactes d'imatge.

No s'ha d'eliminar cap d'aquests directoris, perquè formen part del contracte estructural verificat pels tests del repositori.

## ISO de producció

La fase 12.1 incorpora `config/iso-builder.yaml` i l’ordre `xaac-os build-iso`. La preparació genera `.build/iso/build-iso.sh`, que construeix la ISO híbrida, el hash SHA-256 i la signatura separada.

## IMG de producció

La fase 12.2 incorpora `config/img-builder.yaml` i l’ordre `xaac-os build-img`. La preparació genera el constructor RAW, el manifest i el servei de primer inici per expandir la partició arrel i regenerar la identitat després d'una clonació.

## Fase 12.3 — Paquet PXE

`config/pxe-builder.yaml` i l’ordre `xaac-os build-pxe` preparen el bundle d’arrencada i instal·lació desatesa per xarxa, inclosos el manifest, l’script iPXE i els hashes SHA-256.

## Fase 12.4 — Instal·lador

`config/installer-builder.yaml` i l’ordre `xaac-os build-installer` preparen l’instal·lador de producció. El flux exigeix selecció explícita del disc, frase `INSTALL XAAC`, verificació SHA-256, particionat GPT, còpia del rootfs, instal·lació GRUB UEFI i resum final estructurat.

## Fase 12.5 — Clonació massiva

`config/mass-cloning.yaml` i l’ordre `xaac-os build-cloning` preparen el sanejament de la imatge mestra, els scripts de clonació múltiple i la verificació final. Cada clon regenera la seua identitat al primer inici.

## Fase 12.6 — Proves automatitzades d’imatge

`config/image-tests.yaml` i l’ordre `xaac-os build-image-tests` generen l’executor de validació integral de la imatge, el manifest i l’esquema de l’informe JSON.

## Fase 12.7 — Proves finals de maquinari

`config/hardware-final-tests.yaml` i l’ordre `xaac-os build-hardware-tests` preparen el manifest, l’executor, la llista manual i l’esquema de resultats per validar un Dell Wyse 3040 real.

## Fase 12.8 — Rendiment i estabilitat

`xaac-os-build build-performance-tests` prepara la suite de rendiment per al Dell Wyse 3040.

## Fase 12.10 — Packaging i repositoris

`xaac-os-build build-production-packaging` prepara el manifest, la configuració `reprepro` i el script de publicació signada per als canals laboratory, pilot i production.


## Fase 12.11 — Release candidate

`xaac-os-build build-release-candidate` congela `1.0.0-rc.1` i prepara el manifest, les notes, les portes de qualitat i l’estat d’aprovació bloquejant.
