# Fase 3.6 — USB i perifèrics

## Objectiu

Validar els ports USB i els perifèrics essencials del Dell Wyse 3040 i establir una base controlable per a les polítiques posteriors de quiosc i redirecció FreeRDP.

## Implementació

`UsbDetector` llig exclusivament informació no privilegiada de `/sys/bus/usb/devices`. Detecta els controladors arrel USB 2.0 i USB 3.x, i per a cada dispositiu registra VID/PID, fabricant, producte, versió USB, velocitat, classes d'interfície i estat d'autorització.

Les classes reconegudes són:

- HID;
- emmagatzematge massiu;
- smartcard;
- impressora;
- càmera USB Video Class.

`config/usb.yaml` defineix els mínims de controladors, les classes obligatòries i opcionals, el comportament predeterminat i les llistes VID/PID autoritzades o bloquejades.

## Configuració del rootfs

`configure-usb` genera de manera atòmica:

- `/etc/modules-load.d/xaac-usb.conf`;
- `/etc/udev/rules.d/70-xaac-usb-policy.rules`;
- `/etc/xaac/usb-policy.json`.

Els fitxers no s'escriuen si la destinació és un enllaç simbòlic. Les regles de bloqueig es generen ordenades per garantir construccions reproduïbles.

La política identifica smartcards, impressores i càmeres com a aptes per a redirecció FreeRDP. Aquesta fase no activa encara la redirecció: només deixa el contracte de configuració preparat per als blocs de sessió gràfica, mode quiosc i integració XAAC.

## Ordres

```bash
.venv/bin/xaac-os --root . inspect-usb
.venv/bin/xaac-os --root . --json inspect-usb
.venv/bin/xaac-os --root . inspect-usb --report reports/usb.json
.venv/bin/xaac-os --root . configure-usb --dry-run
.venv/bin/xaac-os --root . configure-usb
```

## Proves de maquinari pendents

Les proves automatitzades validen la detecció i la configuració amb arbres sysfs simulats. La connexió, desconnexió, ús simultani, bloqueig físic i redirecció RDP han de validar-se posteriorment en un Dell Wyse 3040 real.
