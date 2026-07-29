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
