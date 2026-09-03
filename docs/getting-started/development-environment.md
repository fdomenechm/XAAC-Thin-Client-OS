# Entorn de desenvolupament

## Requisits

- Python 3.13
- Git
- utilitats de construcció indicades pels scripts del projecte
- PyCharm o un altre editor compatible amb entorns virtuals

## Preparació

```bash
./scripts/create-venv.sh
```

Per actualitzar un entorn existent:

```bash
./scripts/install-dev.sh
```

L'intèrpret del projecte és `<projecte>/.venv/bin/python`. No s'ha d'afegir `.venv`
al repositori ni al ZIP consolidat.

## Validació

```bash
./scripts/run-tests.sh
./scripts/run-lint.sh
./scripts/run-coverage.sh
```

També es poden utilitzar `make test`, `make lint`, `make coverage` i `make all`.
