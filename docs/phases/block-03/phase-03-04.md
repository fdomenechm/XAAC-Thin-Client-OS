# Fase 3.4 — Xarxa Ethernet

## Objectiu

Validar i configurar de manera determinista la interfície Ethernet integrada del Dell Wyse 3040, mantenint una configuració mínima basada en `systemd-networkd`.

## Implementació

La fase incorpora `config/ethernet.yaml` i el mòdul `ethernet_support.py`.

La inspecció consulta `/sys/class/net` sense requerir privilegis i registra:

- nom estable de la interfície;
- adreça MAC;
- controlador del kernel;
- portadora i estat operatiu;
- velocitat i dúplex;
- indicis de suport Wake-on-LAN.

El perfil accepta els controladors habituals `r8169` i `r8168`, però permet controladors Ethernet alternatius com a advertència per cobrir variants de maquinari.

La configuració del rootfs genera:

- `/etc/systemd/network/10-xaac-ethernet.link`;
- `/etc/systemd/network/20-xaac-ethernet.network`;
- activació de `systemd-networkd.service`.

El mode per defecte és DHCPv4. També es permet IPv4 estàtica amb prefix, passarel·la i un o més DNS validats.

## Ordres

```bash
.venv/bin/xaac-os --root . inspect-ethernet
.venv/bin/xaac-os --root . --json inspect-ethernet
.venv/bin/xaac-os --root . inspect-ethernet --report reports/ethernet.json
.venv/bin/xaac-os --root . configure-ethernet --dry-run
.venv/bin/xaac-os --root . configure-ethernet --mode static \
  --address 192.0.2.10/24 --gateway 192.0.2.1 --dns 192.0.2.53
```

## Criteris de diagnòstic

Són incompatibilitats:

- absència d'una interfície Ethernet requerida;
- velocitat coneguda inferior a 100 Mbps;
- MAC invàlida;
- absència de controlador.

Són advertències no bloquejants:

- cable desconnectat;
- velocitat no disponible en sysfs;
- controlador alternatiu funcional;
- Wake-on-LAN no detectable.

## Limitacions

La prova real de DHCP, IP estàtica, Wake-on-LAN i negociació 100/1000 Mbps necessita maquinari real o una màquina virtual amb xarxa apropiada. Aquesta fase prepara la configuració i els diagnòstics; la integració corporativa avançada correspon al Bloc 7.
