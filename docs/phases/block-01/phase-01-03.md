# Fase 1.3 — CLI del constructor

La CLI `xaac-os` constitueix el punt d'entrada oficial del constructor.

## Ordres

```bash
xaac-os version
xaac-os check-python
xaac-os --root . validate
xaac-os --root . inspect
xaac-os --root . prepare
xaac-os --root . build
xaac-os --root . clean --force
```

L'opció global `--json` ofereix una resposta estructurada per a automatització. `prepare` i
`build` validen la configuració, però no creen encara l'espai de treball; aquesta funció
correspon a la Fase 1.4. La neteja només pot eliminar `.build` i exigeix `--force`.
