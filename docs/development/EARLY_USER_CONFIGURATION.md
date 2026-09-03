# Fase 2.5 — Usuaris, grups i accés administratiu base

Aquesta fase crea de manera determinista els comptes locals inicials del sistema
Debian 13, separant l'administració del compte destinat a la sessió en mode quiosc.

## Objectius

- declarar grups i usuaris en `config/users.yaml`;
- crear `xaac-admin` com a administrador local membre de `sudo`;
- crear `xaac-kiosk` com a compte de sistema sense shell interactiva;
- bloquejar tots els comptes inicials fins que una fase posterior establisca el
  mecanisme segur d'aprovisionament i accés;
- evitar contrasenyes, hashes o secrets dins del repositori i del manifest;
- registrar totes les ordres i el resultat de manera auditable.

## Configuració declarativa

`config/users.yaml` utilitza un esquema versionat. Cada usuari declara el grup
primari, grups suplementaris, shell, directori personal, tipus de compte i estat
de bloqueig. Els grups primaris han d'existir explícitament i no s'admeten noms,
rutes o claus desconegudes.

## Planificació segura

```bash
.venv/bin/xaac-os --root . configure-users --dry-run
```

La planificació no requereix privilegis ni un rootfs complet.

## Execució real

```bash
sudo .venv/bin/xaac-os --root . configure-users
```

Cal executar-la després de `configure-system`. L'operació valida la presència de
Debian, les eines `groupadd`, `useradd` i `usermod`, i les shells declarades.

## Seguretat

Els comptes es creen bloquejats i no es transmet cap secret a la línia d'ordres.
`xaac-kiosk` utilitza `/usr/sbin/nologin`. La configuració, les ordres executades
i els resultats queden registrats en `logs/user-configuration.log` i en el
manifest verificable de la construcció.
