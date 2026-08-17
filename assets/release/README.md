# Claus públiques de releases XAAC

Aquest directori **no ha de contindre mai claus privades**.

La Fase 10.2 admet un únic artefacte opcional de confiança:

```text
assets/release/xaac-archive-keyring.gpg
```

Ha de ser un keyring OpenPGP públic real, exportat des de la clau de signing de releases. Si el fitxer no existeix quan es construeix la ISO, `xaac-update-admin check/update` falla de manera segura (*fail-closed*). El constructor no crea claus, no genera identitats de prova i no relaxa la verificació.

Es pot provisionar el keyring amb:

```bash
./scripts/provision-update-keyring.sh FINGERPRINT
```

La clau privada roman sempre fora del repositori i fora de la ISO.
