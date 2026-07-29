# Fase 10.2 — Repositori APT XAAC

## Objectiu

Definir de manera declarativa, segura i reproduïble l'estructura del repositori APT que publicarà les actualitzacions de XAAC Thin Client OS.

## Abast

La fase configura:

- canals `laboratory`, `pilot` i `production`;
- suites i codis de nom Debian associats;
- component `main` i arquitectura `amd64`;
- estructura `pool/` i `dists/`;
- metadades `Packages`, `Release`, `InRelease` i `Release.gpg`;
- hashes SHA-256 i SHA-512;
- clau de signatura i prohibició de publicació no signada;
- política de retenció i snapshots;
- configuració d'un mirall local verificat.

No inclou encara el servei periòdic de comprovació, descàrrega o staging, previst per a la fase 10.3.

## Ordre

```bash
xaac-os-build configure-xaac-apt-repository
```

Planificació sense escriptura:

```bash
xaac-os-build configure-xaac-apt-repository --dry-run
```

## Fitxers principals

- `config/xaac-apt-repository.yaml`
- `src/xaac_thin_client_os/xaac_apt_repository.py`
- `tests/test_xaac_apt_repository.py`

## Controls de seguretat

- HTTPS obligatori per a publicació i mirall.
- Signatura obligatòria de les metadades Release.
- Rebuig de SHA-1 i MD5.
- Verificació obligatòria de signatures al mirall.
- Rutes absolutes sense traversal.
- Escriptura atòmica i rebuig de destinacions symlink.
