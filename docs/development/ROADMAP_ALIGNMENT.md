# Alineació amb el calendari de desenvolupament 1.0

Després de contrastar el codi consolidat amb el calendari original, s'ha corregit la numeració documental del Bloc 2.

Les capacitats d'instal·lació de paquets, configuració regional, usuaris, xarxa, SSH i nftables ja existents es conserven perquè són útils, però no es consideren fases 2.3-2.8 tancades. Algunes són suport intern del bootstrap i altres anticipen treball dels blocs 4 i 7.

La seqüència oficial del Bloc 2 torna a ser:

1. Bootstrap Debian 13.
2. Repositoris APT.
3. Kernel i initramfs.
4. Arrencada UEFI.
5. Esquema inicial de particions.
6. Sistema base systemd.
7. Localització i consola.
8. Primera imatge arrencable.

Els documents antics s'han reanomenat amb el prefix `EARLY_` per evitar presentar-los com a fases oficials del calendari.
