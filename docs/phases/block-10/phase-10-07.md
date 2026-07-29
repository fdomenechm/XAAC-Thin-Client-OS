# Fase 10.7 — Desplegament per anells

Aquesta fase defineix el desplegament progressiu d'actualitzacions pels anells `laboratory`, `pilot` i `production`.

## Política

`config/update-rings.yaml` estableix l'ordre obligatori dels anells, els percentatges de selecció, el mínim de dispositius, els llindars d'èxit i fallada i el període d'observació. La promoció és seqüencial i requereix aprovació manual i èxit de l'anell anterior.

La selecció de dispositius és determinista a partir de `device_uuid` amb `sha256-modulo-100`, de manera que un dispositiu conserva la mateixa assignació entre comprovacions.

## Controls operatius

El desplegament es pot pausar, reprendre o cancel·lar. La cancel·lació bloqueja noves instal·lacions, però permet finalitzar de manera segura les ja iniciades. Totes les accions exigeixen actor, motiu i marques temporals en l'auditoria.

## Instal·lació

```bash
xaac-os-build configure-update-rings --dry-run
xaac-os-build configure-update-rings
```

Es generen la política efectiva, l'estat persistent, el llançador restringit i la unitat `systemd`. L'orquestració remota concreta des de XMS s'abordarà en la fase 10.8.
