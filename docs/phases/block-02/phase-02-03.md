# Fase 2.3 - Kernel i initramfs

## Objectiu

Instal·lar i validar el kernel Debian del perfil `amd64`, configurar els mòduls necessaris per a l'arrencada inicial i generar un initramfs coherent per a cada versió de kernel present al rootfs.

## Implementació

La fase incorpora `config/kernel.yaml` i el mòdul `kernel_initramfs.py`.

La configuració predeterminada utilitza:

- `linux-image-amd64`;
- `initramfs-tools`;
- compressió `zstd`;
- mòduls d'arrencada per a ext4, EFI/FAT, SATA, NVMe, eMMC/SDHCI i emmagatzematge USB.

L'ordre `configure-kernel` detecta les versions reals en `/lib/modules`, comprova que existeix el `vmlinuz` corresponent i executa `update-initramfs` dins del rootfs. Crea un initramfs nou quan no existeix i l'actualitza quan ja està present.

## Execució

Planificació sense privilegis:

```bash
.venv/bin/xaac-os --root . configure-kernel --dry-run
```

Execució real, després del bootstrap, APT i la instal·lació de paquets:

```bash
sudo .venv/bin/xaac-os --root . configure-kernel
```

## Seguretat i idempotència

- es rebutgen rootfs insegurs;
- es valida estrictament l'esquema YAML;
- no s'escriu sobre enllaços simbòlics;
- els fitxers es generen de forma atòmica amb permisos `0644`;
- la regeneració usa `-u` quan l'initramfs ja existeix;
- es comprova el resultat final en `/boot/initrd.img-*`;
- el mode `--dry-run` no requereix ni kernel instal·lat ni privilegis.

## Traçabilitat

El manifest incorpora paquets, compressió, mòduls, versions detectades, ordres i estat. El log queda en `logs/kernel-initramfs.log`.

## Criteri de tancament

El rootfs conté un kernel Debian i un initramfs coherent per a cadascuna de les versions instal·lades.
