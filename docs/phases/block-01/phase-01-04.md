# Fase 1.4 — Espai de treball de construcció

La fase incorpora un espai de treball segur i aïllat dins de `.build/`.

Cada execució de `xaac-os prepare` o `xaac-os build` crea:

```text
.build/
├── current
└── runs/
    └── <build-id>/
        ├── artifacts/
        ├── logs/
        ├── tmp/
        └── manifest.json
```

El `build-id` combina una marca temporal UTC i un component aleatori. El fitxer
`.build/.lock` s'obté de manera atòmica i impedeix construccions concurrents.
El manifest inicial es genera també de manera atòmica.

## Ús

```bash
xaac-os --root . prepare
xaac-os --root . --json prepare
xaac-os --root . clean --force
```

La neteja queda restringida a `.build` i es rebutja mentre existisca un bloqueig.
