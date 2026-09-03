# Fase 2.4 — Identitat i configuració regional del sistema

Aquesta fase configura de manera determinista la identitat bàsica i els paràmetres
regionals del rootfs Debian 13 després de la instal·lació del sistema base.

## Objectius

- definir el nom d'host del thin client;
- generar `/etc/hostname` i `/etc/hosts` coherents;
- habilitar `ca_ES.UTF-8`, `es_ES.UTF-8` i `en_US.UTF-8`;
- establir `ca_ES.UTF-8` com a locale principal;
- configurar la zona horària `Europe/Madrid`;
- executar `locale-gen` dins del rootfs;
- registrar el pla i el resultat al manifest de construcció.

## Configuració declarativa

Els valors resideixen en `config/system.yaml`. El fitxer té esquema versionat,
rebutja claus desconegudes i valida hostname, locales i zona horària.

## Planificació segura

```bash
.venv/bin/xaac-os --root . configure-system --dry-run
```

No exigeix privilegis ni modifica el rootfs.

## Execució real

```bash
sudo .venv/bin/xaac-os --root . configure-system
```

Cal haver executat prèviament `bootstrap`, `configure-apt` i `install-packages`.
L'operació valida la presència de Debian, `locale-gen` i el fitxer de zona horària.

## Seguretat i reproduïbilitat

Els fitxers regulars s'escriuen de manera atòmica. No se sobreescriuen enllaços
simbòlics inesperats i `/etc/localtime` es crea explícitament contra el fitxer de
zona horària del rootfs. Tota l'activitat queda en `logs/system-configuration.log`.
