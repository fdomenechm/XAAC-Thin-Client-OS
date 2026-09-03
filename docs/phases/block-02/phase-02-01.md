# Fase 2.1 — Bootstrap Debian 13

Aquesta fase incorpora la creació del sistema de fitxers arrel mínim de Debian 13
(`trixie`) mitjançant `debootstrap` i la variant `minbase`.

## Objectius

- construir sempre dins de `.build/runs/<build-id>/rootfs`;
- utilitzar l'arquitectura, suite, mirror i components declarats en `config/build.yaml`;
- registrar l'ordre exacta i tota l'eixida en `logs/debootstrap.log`;
- exigir privilegis de `root` només en l'execució real;
- eliminar automàticament un `rootfs` parcial quan hi ha errors;
- conservar opcionalment l'arbre parcial amb `--keep-partial` per al diagnòstic;
- incorporar el pla i l'estat del bootstrap al manifest verificable.

## Dependència de l'amfitrió

En Debian o derivats:

```bash
sudo apt install debootstrap
```

## Validació sense modificar el sistema

```bash
.venv/bin/xaac-os --root . bootstrap --dry-run
```

Aquesta ordre crea un nou espai de treball, valida tota la configuració i registra
el pla, però no executa `debootstrap` ni necessita privilegis.

## Execució real

```bash
sudo .venv/bin/xaac-os --root . bootstrap
```

El resultat queda en:

```text
.build/runs/<build-id>/rootfs/
```

El log complet queda en:

```text
.build/runs/<build-id>/logs/debootstrap.log
```

Per conservar un sistema parcial en cas d'error:

```bash
sudo .venv/bin/xaac-os --root . bootstrap --keep-partial
```

## Disseny comprovable

`BootstrapPlan` és immutable i genera l'ordre exacta de forma determinista.
`BootstrapRunner` encapsula privilegis, execució, logs, validació del marcador
`/etc/debian_version` i neteja. Això permet provar tota la lògica sense xarxa ni
execució real de `debootstrap`.
