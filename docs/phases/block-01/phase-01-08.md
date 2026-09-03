# Fase 1.8 — Manifest de construcció

Cada execució de `prepare` o `build` genera un `manifest.json` complet dins de
`.build/runs/<build-id>/`.

El manifest registra la versió, el perfil, el canal, Debian, els formats de la
imatge, els paquets efectius, els repositoris APT, el commit Git quan existeix,
els hashes SHA-256 de totes les entrades declaratives i els hashes dels fitxers
generats i logs dels hooks.

El camp `integrity.manifest` protegeix el contingut complet del manifest amb un
hash SHA-256 calculat sobre una serialització JSON canònica. La funció
`verify_manifest()` permet comprovar-lo posteriorment.
