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
