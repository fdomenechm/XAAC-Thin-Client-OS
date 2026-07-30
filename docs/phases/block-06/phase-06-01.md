# Fase 6.1 — Paquet XAAC Thin Client

## Objectiu

Integrar de manera verificable el paquet Debian de XAAC Thin Client dins del rootfs de XAAC Thin Client OS, sense incorporar artefactes binaris temporals al repositori consolidat.

## Implementació

- Perfil declaratiu `config/xaac-thin-client-package.yaml`.
- Artefacte esperat: `packages/xaac-thin-client_1.0.0_amd64.deb`.
- Inspecció real amb `dpkg-deb` del nom, versió, arquitectura i dependències.
- Càlcul SHA-256 i verificació opcional contra un hash fixat.
- Política de versió que admet només la versió prevista o revisions patch posteriors compatibles.
- Validació de dependències mínimes GTK 4 / Python.
- Còpia atòmica al rootfs i generació de metadades auditables.
- Preferència APT del canal `stable` i instal·lació mínima sense `Recommends`.
- Ordre CLI `install-xaac-thin-client` amb `--dry-run`.
- Protecció contra rutes insegures, artefactes absents, downgrades i enllaços simbòlics.

## Ús

1. Copiar el `.deb` publicat al camí configurat.
2. Preparar o carregar un workspace amb rootfs.
3. Validar i planificar:

```bash
xaac-os --root . install-xaac-thin-client --dry-run
```

4. Instal·lar dins del rootfs:

```bash
sudo xaac-os --root . install-xaac-thin-client
```

## Proves

La suite cobreix càrrega del perfil, inspecció de metadades, versió, arquitectura, dependències, absència de l’artefacte, idempotència funcional, `dry-run`, instal·lació i protecció contra symlinks.

## Limitació coneguda

El ZIP consolidat no inclou el paquet `.deb`, d’acord amb les regles del calendari. La construcció real requereix col·locar prèviament un paquet publicat i, quan estiga disponible, fixar el seu SHA-256 al perfil.
