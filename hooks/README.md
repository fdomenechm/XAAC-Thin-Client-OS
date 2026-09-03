# Hooks de construcció

Aquest directori conté els punts d'extensió del procés de construcció de XAAC Thin Client OS.

Cada subdirectori correspon a una etapa definida pel sistema de hooks:

- `pre-bootstrap/`
- `post-bootstrap/`
- `pre-packages/`
- `post-packages/`
- `pre-image/`
- `post-image/`

Els directoris han d'existir encara que una etapa no tinga hooks configurats.

Consulteu també la [referència de configuració](../docs/reference/configuration.md).
