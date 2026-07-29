# Fase 2.8 — Primera imatge arrencable

## Objectiu

Integrar en un únic artefacte el root filesystem Debian 13, l'esquema GPT, el kernel,
l'initramfs, l'arrencada UEFI i el manifest de construcció.

## Ordre

```bash
sudo .venv/bin/xaac-os --root . build-image
```

Planificació no destructiva:

```bash
.venv/bin/xaac-os --root . build-image --dry-run
```

## Artefactes

La construcció genera dins de l'espai de treball actual:

- `artifacts/xaac-thin-client-os.img`;
- `artifacts/xaac-thin-client-os.img.gz`;
- `artifacts/xaac-thin-client-os.img.sha256`;
- `logs/bootable-image.log`.

## Flux d'assemblatge

1. valida el rootfs, `fstab`, kernel i initramfs;
2. crea una imatge dispersa de 7168 MiB;
3. associa un dispositiu loop amb escaneig de particions;
4. crea la taula GPT declarada en `config/partitions.yaml`;
5. formata EFI, arrel, dades i recuperació;
6. copia el rootfs preservant permisos, ACL, atributs i identificadors numèrics;
7. munta les particions persistents dins de l'arrel;
8. instal·la GRUB x86_64 EFI en mode extraïble i sense modificar NVRAM;
9. sincronitza i desmunta en ordre invers;
10. desacobla el dispositiu loop;
11. comprimeix de manera determinista amb gzip;
12. genera hashes SHA-256 de la imatge i de la còpia comprimida;
13. registra artefactes i hashes en el manifest.

## Seguretat

- l'execució real exigeix privilegis de root;
- només escriu dins del directori d'artefactes de l'espai de treball;
- rebutja artefactes preexistents;
- sempre intenta desmuntar i desacoblar el loop en cas d'error;
- `--dry-run` no crea imatges ni necessita privilegis.

## Limitacions de validació

La suite automatitzada simula les operacions privilegiades. L'arrencada UEFI real en QEMU/OVMF
i en Dell Wyse 3040 requereix un entorn amb virtualització o maquinari real i queda marcada com
a validació externa del lliurable.


## Correcció d’integració del flux complet

L’ordre `build-image` no depén d’un `rootfs` creat en una execució temporal anterior.
Quan `.build/current` no existeix, apunta a una execució incompleta o no conté Debian,
`fstab`, kernel i initramfs, el constructor crea un `build-id` nou i executa totes les
etapes necessàries del Bloc 2 dins del mateix espai de treball. Això evita l’error
`Rootfs inexistent o insegur` després d’executar tests, neteges o dry-runs.

## Dependències de l'amfitrió

La construcció real valida totes les eines abans de crear cap artefacte. Es poden instal·lar amb:

```bash
./scripts/install-build-dependencies.sh
```

La comprovació és conjunta i aborta abans del bootstrap si falta qualsevol ordre. `--dry-run` no executa aquesta comprovació perquè ha de continuar sent offline i no privilegiat.
