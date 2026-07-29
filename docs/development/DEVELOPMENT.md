# Entorn de desenvolupament

## Versió de Python

El projecte requereix exclusivament Python 3.13. La versió mínima i màxima compatible
queda declarada en `pyproject.toml`.

## Creació de `.venv`

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## PyCharm

1. Obrir el directori arrel del projecte.
2. Accedir a **Settings → Project → Python Interpreter**.
3. Seleccionar **Add Interpreter → Existing**.
4. Indicar `.venv/bin/python`.
5. Marcar `src` com a **Sources Root** si PyCharm no ho detecta automàticament.
6. Configurar `pytest` com a test runner predeterminat.

Els fitxers `.idea/` són locals i no formen part del repositori consolidat.

## Comprovacions

```bash
.venv/bin/python -m pytest
.venv/bin/python -m pytest --cov=xaac_thin_client_os
.venv/bin/ruff check src tests
.venv/bin/mypy src
```
