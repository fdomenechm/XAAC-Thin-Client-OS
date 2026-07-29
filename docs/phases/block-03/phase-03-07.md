# Fase 3.7 — Energia i temperatura

Aquesta fase incorpora un perfil declaratiu per al Dell Wyse 3040, detecció dels governors de CPU, sensors tèrmics, dispositius watchdog i arrencada UEFI.

La configuració desactiva suspensió, hibernació i modes híbrids en el terminal quiosc, configura el watchdog de systemd i registra els llindars tèrmics i la política esperada després d'una pèrdua de corrent. L'opció real «Restore on AC Power Loss» depén del firmware UEFI i s'ha de validar físicament.

```bash
.venv/bin/xaac-os --root . inspect-power
.venv/bin/xaac-os --root . --json inspect-power
.venv/bin/xaac-os --root . inspect-power --report reports/power.json
.venv/bin/xaac-os --root . configure-power --dry-run
.venv/bin/xaac-os --root . configure-power
```

Les proves de càrrega sostinguda, temperatura real, apagada, reinici i pèrdua d'alimentació requereixen un Wyse 3040 físic.
