# Construcció d'imatges i artefactes

## Principis

La construcció és declarativa, auditable i reproduïble. Els fitxers temporals es
generen a `.build/`, directori que no forma part del codi font consolidat.

## Validació prèvia

```bash
.venv/bin/xaac-os --root . validate
.venv/bin/xaac-os --root . inspect
.venv/bin/xaac-os --root . prepare
```

Utilitzeu `--dry-run` sempre que l'ordre l'admeta. Les operacions destructives s'han
d'executar únicament sobre un entorn de construcció dedicat.

## Constructors principals

```bash
.venv/bin/xaac-os --root . build-iso
.venv/bin/xaac-os --root . build-img
.venv/bin/xaac-os --root . build-pxe
.venv/bin/xaac-os --root . build-installer
.venv/bin/xaac-os --root . build-cloning
```

## Validació de la release

```bash
.venv/bin/xaac-os --root . build-image-tests
.venv/bin/xaac-os --root . build-hardware-tests
.venv/bin/xaac-os --root . build-performance-tests
.venv/bin/xaac-os --root . build-documentation
.venv/bin/xaac-os --root . build-production-packaging
.venv/bin/xaac-os --root . build-release-candidate
.venv/bin/xaac-os --root . build-final-release
```

La publicació oficial requereix l'aprovació de la release candidate, els artefactes
reals, els hashes SHA-256 i signatures creades amb una clau privada autoritzada.
