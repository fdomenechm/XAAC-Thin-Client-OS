# Fase 3.5 — Àudio

## Objectiu

Configurar i diagnosticar l'àudio del Dell Wyse 3040 amb una pila mínima basada en ALSA i PipeWire, preparada tant per a reproducció local com per a la futura redirecció RDP.

## Implementació

- Perfil declaratiu `config/audio.yaml`.
- Lectura de `/proc/asound/cards` i `/proc/modules` sense requerir privilegis.
- Detecció de targetes HDMI/DisplayPort, dispositius analògics i entrades de micròfon.
- Validació del controlador `snd_hda_intel` o `snd_hdmi_lpe_audio`.
- Comprovació de la disponibilitat de PipeWire o WirePlumber.
- Generació de:
  - `/etc/modules-load.d/xaac-audio.conf`;
  - `/etc/modprobe.d/xaac-audio.conf`;
  - `/etc/xaac/audio.conf`.
- Informes JSON escrits de manera atòmica.
- Rebuig d'escriptures sobre enllaços simbòlics.

## Criteris

L'absència d'ALSA, del controlador o d'una eixida HDMI/DisplayPort és incompatible. L'absència de jack, micròfon o PipeWire durant una inspecció preliminar es considera advertència, perquè poden variar segons la revisió del dispositiu o l'estat del rootfs.

## Ordres

```bash
.venv/bin/xaac-os --root . inspect-audio
.venv/bin/xaac-os --root . --json inspect-audio
.venv/bin/xaac-os --root . inspect-audio --report reports/audio.json
.venv/bin/xaac-os --root . configure-audio --dry-run
.venv/bin/xaac-os --root . configure-audio
```

## Proves

La fase afegeix proves positives, negatives, de perfil, detecció, dispositius opcionals, configuració, escriptura atòmica, seguretat de rutes i integració CLI.
