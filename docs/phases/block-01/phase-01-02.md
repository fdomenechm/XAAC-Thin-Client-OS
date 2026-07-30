# Fase 1.2 — Model de configuració del constructor

## Objectiu

Definir una configuració declarativa, tipada i validada per a les futures construccions
de XAAC Thin Client OS.

## Fitxers principals

- `config/build.yaml`: versió, arquitectura, canal, perfil, Debian i imatge.
- `config/packages.yaml`: grups de paquets i exclusions.
- `config/repositories.yaml`: repositoris APT signats.
- `profiles/common/profile.yaml`: valors comuns de maquinari.
- `profiles/wyse3040/profile.yaml`: perfil inicial del Dell Wyse 3040.

## API Python

El paquet `xaac_thin_client_os.configuration` proporciona models immutables i el
carregador `load_project_configuration(root)`. La càrrega utilitza `yaml.safe_load`
i rebutja camps desconeguts, rutes insegures, URLs APT sense HTTPS, duplicats,
versions incompatibles i inconsistències entre fitxers.

## Validació manual

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from xaac_thin_client_os.configuration import load_project_configuration

print(load_project_configuration(Path('.')))
PY
```

La CLI completa del constructor es desenvoluparà en la Fase 1.3.
