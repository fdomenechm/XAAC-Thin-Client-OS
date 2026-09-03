# Fase 2.4 — Arrencada UEFI

## Objectiu

Preparar el root filesystem Debian 13 perquè puga arrancar en equips UEFI amd64 mitjançant GRUB, sense avançar encara la creació física de particions de la Fase 2.5.

## Implementació

- Configuració declarativa en `config/uefi.yaml`.
- Paquets `grub-efi-amd64-bin` i `grub2-common` incorporats al sistema base.
- Ordre `configure-uefi` amb mode `--dry-run`.
- Instal·lació GRUB amb target `x86_64-efi`.
- ESP prevista en `/boot/efi`.
- Instal·lació sense modificar NVRAM (`--no-nvram`).
- Generació del fallback estàndard `EFI/BOOT/BOOTX64.EFI` (`--removable`).
- Menú ocult, timeout mínim i `os-prober` desactivat.
- Regeneració de `/boot/grub/grub.cfg`.
- Validació de parelles coherents kernel/initramfs.
- Log i manifest verificable.

## Ús

```bash
.venv/bin/xaac-os --root . configure-uefi --dry-run
sudo .venv/bin/xaac-os --root . configure-uefi
```

La seqüència prevista és `bootstrap`, `configure-apt`, `install-packages`, `configure-kernel` i `configure-uefi`.

## Límits de la fase

Aquesta fase prepara el carregador UEFI dins del rootfs i d'una ESP muntada en `/boot/efi`. La creació, mida, format i muntatge real de la partició EFI pertanyen a la Fase 2.5.

## Criteri de tancament

La configuració genera `BOOTX64.EFI` i `grub.cfg`, conserva una entrada coherent per al kernel i initramfs instal·lats i queda completament registrada al manifest.
