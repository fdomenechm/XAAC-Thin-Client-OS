# XAAC Thin Client OS

**XAAC Thin Client OS 1.0.0** és una distribució especialitzada basada en Debian 13,
optimitzada per al Dell Wyse 3040 amb 2 GB de RAM i 8 GB d'eMMC. Proporciona una
sessió gràfica segura en mode quiosc per executar XAAC Thin Client, XAAC Thin Client
Agent i el client personalitzat XAAC Remote Support basat en RustDesk.

## Estat del projecte

- Versió estable: **1.0.0**
- Plataforma base: **Debian 13**
- Arquitectura objectiu: **amd64**
- Maquinari principal: **Dell Wyse 3040**
- Entorn de desenvolupament: **Python 3.13**
- Llicència: **EUPL v1.2 o posterior**

El calendari inicial de desenvolupament està complet. L'històric de les fases es
conserva a [`docs/phases/`](docs/phases/README.md).

## Característiques principals

- Sessió dedicada `xaac-kiosk` amb inici automàtic i restriccions de quiosc.
- Administració local separada mitjançant `xaac-admin`.
- Accés OpenSSH restringit per usuari, clau i xarxes autoritzades.
- Integració amb XAAC Thin Client, XAAC Agent i XAAC Remote Support.
- Configuració declarativa YAML i aplicació transaccional amb rollback.
- Hardening amb systemd, AppArmor, nftables, sysctl i control de dispositius.
- Actualitzacions signades, desplegament per anells i recuperació en diversos nivells.
- Constructors per a ISO, IMG, PXE, instal·lador, clonació i release final.
- Proves automatitzades de codi, imatge, maquinari, rendiment i estabilitat.

## Inici ràpid de desenvolupament

```bash
./scripts/create-venv.sh
./scripts/run-tests.sh
.venv/bin/xaac-os version
.venv/bin/xaac-os --root . validate
```

Python ha de ser 3.13. El projecte declara la restricció `>=3.13,<3.14`.

## Construcció

La configuració es troba principalment a `config/*.yaml` i als perfils de
`profiles/`. Les operacions destructives exigeixen privilegis, confirmació explícita
i un entorn preparat. Exemples:

```bash
.venv/bin/xaac-os --root . prepare
.venv/bin/xaac-os --root . bootstrap --dry-run
.venv/bin/xaac-os --root . build-iso
.venv/bin/xaac-os --root . build-img
.venv/bin/xaac-os --root . build-final-release
```

Consulteu la [guia de construcció](docs/getting-started/build.md) abans d'executar
constructors reals.

## Documentació

El punt d'entrada oficial és [`docs/README.md`](docs/README.md).

- [Instal·lació i primers passos](docs/getting-started/README.md)
- [Administració i operació](docs/administration/README.md)
- [Arquitectura](docs/architecture/README.md)
- [Desenvolupament](docs/development/README.md)
- [Referència tècnica](docs/reference/README.md)
- [Release 1.0.0](docs/release/README.md)
- [Històric de fases](docs/phases/README.md)

## Estructura del repositori

```text
src/          codi Python del constructor i de la CLI
tests/        proves automatitzades
config/       configuració declarativa del sistema
profiles/     perfils comuns i del Dell Wyse 3040
builder/      recursos del constructor d'imatges
templates/    plantilles del sistema
hooks/        hooks controlats de construcció
packaging/    definicions dels paquets Debian
recovery/     recursos de recuperació
docs/         documentació oficial i històrica
scripts/      scripts de desenvolupament i construcció
```

## Seguretat i secrets

No s'han d'incloure claus privades, tokens, credencials, certificats particulars ni
identitats de dispositiu en el repositori, en la imatge mestra o en els ZIP
consolidats. Les signatures oficials es generen únicament amb una clau autoritzada
fora del codi font.

## Llicència

European Union Public Licence (EUPL) v1.2 o posterior.

## Generació de la ISO des de PyCharm

Des del terminal integrat de PyCharm, situat a l'arrel del projecte:

```bash
sudo ./scripts/install-build-dependencies.sh
./scripts/build-production-iso.sh
```

El segon script eleva privilegis amb `sudo`, construeix el rootfs Debian 13,
genera el SquashFS, prepara GRUB i crea la ISO híbrida BIOS/UEFI. L'artefacte
final queda en:

```text
.build/artifacts/xaac-thin-client-os-amd64.iso
```

La ISO de desenvolupament es pot generar sense clau GPG. Per exigir signatura:

```bash
XAAC_ISO_SIGNING_KEY=<ID_CLAU> XAAC_REQUIRE_ISO_SIGNATURE=1 \
  ./scripts/build-production-iso.sh
```
