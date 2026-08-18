# Guia de recuperació

## Recuperació normal

Comproveu primer l'estat:

```bash
sudo xaac-recovery status
```

Si una actualització ha deixat una versió funcionalment incorrecta i existeix un punt de recuperació:

```bash
sudo xaac-recovery rollback --yes
```

Aquesta operació restaura conjuntament els paquets XAAC i la configuració guardada en el punt de recuperació.

## Mode de recuperació local

1. Engegueu o reinicieu el terminal.
2. Premeu `Esc` immediatament després del firmware per mostrar el menú GRUB ocult.
3. Seleccioneu **XAAC Thin Client OS — Recovery**.
4. Inicieu sessió en `tty1` amb `xaac-admin`.
5. Executeu `sudo xaac-recovery menu`.

El mode recovery no arranca el quiosc, la VPN ni l'Agent. NetworkManager també roman desactivat fins que l'administrador l'activa explícitament.

## Reparació

Des del mode recovery:

```bash
sudo xaac-recovery repair --yes
```

La reparació reconfigura paquets pendents, valida `dpkg`, regenera initramfs i torna a generar GRUB. No executa `fsck` sobre l'arrel muntada i no descarrega paquets de xarxa de manera implícita.

Per restaurar només la configuració de l'últim punt segur:

```bash
sudo xaac-recovery repair --restore-configuration --yes
```

## Xarxa opcional

```bash
sudo xaac-recovery network-on --yes
sudo xaac-recovery network-off --yes
```

Activeu-la només quan siga necessària per al diagnòstic o suport.

## Factory reset

No està habilitat en la Fase 10.4. Només s'incorporarà quan existisca una imatge factory independent, versionada, signada i validada físicament. No utilitzeu els prototips històrics del repositori com a mecanisme de producció.

## Evidències

Conserveu el bundle de `xaac-maintenance diagnostics` i l'auditoria de `/var/log/xaac-recovery/`. No copieu secrets, claus privades, tokens OTP o credencials VPN en incidències.
