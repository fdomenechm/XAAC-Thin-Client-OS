# Fase 12.2 — Constructor IMG

Aquesta fase incorpora la generació determinista d'una imatge de disc directa per a Dell Wyse 3040.

## Funcionalitats

- Imatge RAW de 7,5 GiB amb taula GPT i arrencada UEFI.
- Particions EFI, arrel, dades persistents i recuperació.
- Constructor preparat amb `xaac-os build-img`.
- Compressió XZ i fitxer SHA-256.
- Expansió de la partició arrel al primer inici.
- Eliminació de la identitat de la imatge mestra.
- Regeneració de `machine-id`, claus SSH i identitat XAAC després de clonar.

La preparació és testable sense privilegis. L'execució de `.build/img/build-img.sh` requereix `sgdisk`, `losetup`, eines de sistemes de fitxers, `xz` i permisos d'administrador.
