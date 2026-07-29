# Constructor de la imatge

Aquest directori forma part de l'estructura obligatòria de XAAC Thin Client OS i agrupa els recursos auxiliars del constructor d'imatges.

Els subdirectoris es conserven versionats encara que temporalment no continguen implementacions:

- `auto/`: configuració automatitzada del constructor.
- `hooks/`: punts d'extensió específics del procés de construcció.
- `scripts/`: scripts interns del constructor.
- `templates/`: plantilles utilitzades per generar artefactes d'imatge.

No s'ha d'eliminar cap d'aquests directoris, perquè formen part del contracte estructural verificat pels tests del repositori.
