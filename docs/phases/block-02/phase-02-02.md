# Fase 2.2 — Configuració APT del rootfs

Aquesta fase configura de manera determinista i segura els repositoris APT del
sistema Debian 13 creat en la Fase 2.1.

## Objectius

- generar repositoris en format modern Deb822;
- utilitzar exclusivament els repositoris habilitats en `config/repositories.yaml`;
- exigir HTTPS i un keyring declarat amb `Signed-By`;
- limitar els repositoris a l'arquitectura objectiu;
- desactivar `Recommends`, `Suggests` i descàrregues de traduccions;
- evitar modificacions fora del rootfs de la construcció;
- rebutjar enllaços simbòlics en els fitxers gestionats;
- registrar els fitxers i l'estat en el manifest verificable.

## Validació sense modificar el rootfs

Després d'haver creat o planificat un bootstrap:

```bash
.venv/bin/xaac-os --root . configure-apt --dry-run
```

El pla complet queda en:

```text
.build/runs/<build-id>/logs/apt-configuration.log
```

## Execució real

Després d'un bootstrap real:

```bash
sudo .venv/bin/xaac-os --root . configure-apt
```

Es generen:

```text
/etc/apt/sources.list.d/xaac.sources
/etc/apt/apt.conf.d/99xaac-minimal
/etc/apt/sources.list
```

Les rutes anteriors són sempre relatives al rootfs de la construcció, no al
sistema amfitrió.

## Política minimalista

La configuració desactiva la instal·lació automàtica de paquets recomanats i
suggerits, evita índexs de traduccions i fixa tres reintents de descàrrega.
Aquesta política redueix consum d'espai i trànsit, especialment important en el
Dell Wyse 3040 amb 8 GB d'eMMC.
