# Fase 1.1 — Inicialització del repositori

## Resultat

La fase estableix la base tècnica del projecte XAAC Thin Client OS.

## Implementació

- Python restringit a la sèrie 3.13.
- Estructura de paquet basada en `src/`.
- Configuració centralitzada en `pyproject.toml`.
- Entorn local `.venv` documentat i exclòs de Git.
- Configuració de PyCharm documentada.
- CLI inicial `xaac-os`.
- Metadades i versió canònica en `VERSION`.
- Estructura inicial de constructor, perfils, paquets, configuració i recuperació.
- Llicència GPL-3.0-or-later.
- Scripts operatius estàndard en `scripts/`.
- `Makefile` per executar les operacions habituals.

## Validació executada

```text
18 tests passed
Cobertura total: 95.16 %
Python utilitzat: 3.13.5
```

També s'ha verificat la compilació de tots els mòduls Python amb `compileall`.

## Limitacions deliberades

Aquesta fase no implementa encara el constructor d'imatges ni la configuració declarativa.
Aquests elements corresponen a les fases 1.2 i següents.
