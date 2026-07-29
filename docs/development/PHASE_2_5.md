# Fase 2.5 — Esquema inicial de particions

## Objectiu

Definir i aplicar de manera segura el primer esquema GPT de XAAC Thin Client OS per a un dispositiu de 8 GB, mantenint espai per a UEFI, sistema arrel, dades persistents i recuperació.

## Esquema

| Núm. | Etiqueta | Mida | Sistema | Muntatge |
|---:|---|---:|---|---|
| 1 | `XAAC_EFI` | 256 MiB | FAT32 | `/boot/efi` |
| 2 | `XAAC_ROOT` | 4608 MiB | ext4 | `/` |
| 3 | `XAAC_DATA` | 1536 MiB | ext4 | `/var/lib/xaac` |
| 4 | `XAAC_RECOVERY` | 700 MiB | ext4 | `/recovery` |

La mida total declarada és de 7168 MiB, deixant marge per a metadades GPT, alineació i diferències reals entre capacitat comercial i útil de l'eMMC.

## Configuració

La font declarativa és `config/partitions.yaml`. El constructor valida:

- esquema GPT;
- quatre particions exactes;
- numeració i etiquetes úniques;
- alineació;
- suma de mides;
- sistemes de fitxers autoritzats;
- punts de muntatge segurs;
- existència obligatòria d'EFI, arrel, dades i recuperació.

## Seguretat

L'ordre real és destructiva i exigeix simultàniament:

- un dispositiu absolut sota `/dev`;
- privilegis de root;
- que el dispositiu siga realment de bloc;
- l'opció explícita `--confirm-destructive`.

El mode `--dry-run` no modifica el disc ni genera `/etc/fstab`.

## Execució

```bash
.venv/bin/xaac-os --root . configure-partitions \
  --device /dev/mmcblk0 \
  --dry-run
```

Execució real:

```bash
sudo .venv/bin/xaac-os --root . configure-partitions \
  --device /dev/mmcblk0 \
  --confirm-destructive
```

## Resultats

El procés genera una taula GPT amb `sgdisk`, força la relectura amb `partprobe`, crea FAT32/ext4 i escriu `/etc/fstab` de manera atòmica utilitzant etiquetes estables.

Els UUID reals són generats pels sistemes de fitxers i es mantenen únics. En aquesta fase `fstab` usa etiquetes estables; la materialització d'imatges i la verificació explícita d'UUID es completarà en la Fase 2.8.
