# Guia de desenvolupament

## Entorn
Python 3.13, entorn virtual `.venv`, pytest i configuració declarativa YAML. El projecte es construeix de manera incremental des de l’últim ZIP consolidat.

## Flux de treball
1. Creeu o activeu `.venv`.
2. Instal·leu el projecte amb dependències de desenvolupament.
3. Executeu la suite completa abans i després de cada canvi.
4. Afegiu proves positives, negatives, límits, errors, idempotència i permisos.
5. Actualitzeu documentació i `CHANGELOG.md`.

## Consolidació
El ZIP no inclou `.git`, `.build`, caches, entorns virtuals, imatges, paquets temporals, secrets, logs ni cobertura. Sí inclou codi, tests, configuracions, scripts, plantilles, packaging i documentació.

## Constructors de producció
Useu `build-iso`, `build-img`, `build-pxe`, `build-installer`, `build-cloning`, `build-image-tests`, `build-hardware-tests` i `build-performance-tests` segons el lliurable.
