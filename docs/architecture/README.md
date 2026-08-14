# Arquitectura de XAAC Thin Client OS

## Visió general

XAAC Thin Client OS és una imatge Debian 13 mínima i especialitzada. Separa la
sessió d'usuari, l'administració, la gestió central i el suport remot.

```text
Firmware UEFI
  └─ GRUB / recuperació
      └─ Debian 13 minimal
          ├─ systemd, nftables, AppArmor i sysctl
          ├─ xarxa i identitat del dispositiu
          ├─ XAAC Thin Client Agent
          ├─ sessió gràfica xaac-kiosk
          │   └─ XAAC Thin Client
          └─ XAAC Remote Support (activació controlada)
```

## Components

- **Constructor Python**: valida configuracions i prepara rootfs, imatges i releases.
- **Configuració declarativa**: YAML sota `config/` i perfils sota `profiles/`.
- **Sessió de quiosc**: compte dedicat, compositor i supervisor amb restriccions.
- **Agent**: identitat, inventari, enrolament, polítiques, estat i diagnòstic.
- **Suport remot**: RustDesk personalitzat, desactivat per defecte i auditable.
- **Actualització i recuperació**: verificació criptogràfica, staging, rollback i diversos nivells de recuperació.

## Decisions de disseny

- Mínim privilegi i separació estricta de comptes.
- Cap secret estàtic en la imatge mestra.
- Primer inici idempotent per regenerar identitat després de clonació.
- Escriptures controlades i protecció contra rutes insegures i enllaços simbòlics.
- Operacions destructives amb confirmació explícita.
- Artefactes finals verificables mitjançant manifests, hashes i signatures.

## Integracions

- [Administració i enrolament de XAAC Agent](agent-enrollment.md)
La documentació específica de XAAC Remote Support es troba a [`integrations/`](integrations/).
