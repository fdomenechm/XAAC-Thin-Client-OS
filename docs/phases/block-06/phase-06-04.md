# Fase 6.4 — Servei de primer inici

## Objectiu

Configurar un servei `systemd` d'execució única que valide el maquinari, genere o valide la identitat persistent del dispositiu i deixe un estat auditable abans d'arrancar XAAC Agent i la sessió gràfica.

## Implementació

- Perfil declaratiu `config/first-boot.yaml`.
- Ordre `xaac-os configure-first-boot` amb mode `--dry-run`.
- Unitat `xaac-first-boot.service` habilitada en `multi-user.target`.
- Execució anterior a `xaac-agent.service` i `greetd.service`.
- Validació del model Dell Wyse 3040, RAM mínima i presència d'eMMC.
- Integració amb el gestor d'identitat de la fase 6.3.
- Estat persistent `completed` o `failed` en JSON.
- Marcador de finalització que garanteix idempotència.
- Configuració i escriptures atòmiques amb permisos restrictius.
- Enduriment inicial de la unitat systemd.

## Execució

```bash
xaac-os --root . configure-first-boot --dry-run
xaac-os --root . configure-first-boot
```

## Estat en el dispositiu

- `/etc/xaac/first-boot.yaml`
- `/etc/xaac/device-identity.yaml`
- `/var/lib/xaac-agent/first-boot/state.json`
- `/var/lib/xaac-agent/first-boot/completed`

## Limitacions

La validació definitiva requereix una arrencada sobre un Dell Wyse 3040 real. Les proves automatitzades simulen DMI, memòria i eMMC dins d'un rootfs temporal.
