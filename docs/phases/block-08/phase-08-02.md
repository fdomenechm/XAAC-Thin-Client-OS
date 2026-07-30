# Fase 8.2 — Branding de RustDesk XAAC

Aquesta fase defineix una identitat visual i textual separada de la configuració operativa de RustDesk.

Inclou el nom **XAAC Remote Support**, identificadors d'aplicació, icona i logotip SVG, textos visibles,
etiquetes dels servidors gestionats i informació de versió. No configura encara adreces de servidor,
claus, proxy ni polítiques de connexió; aquests elements corresponen a la fase 8.3.

La configuració es genera amb:

```bash
xaac-os configure-rustdesk-branding
```

Per validar sense escriure al rootfs:

```bash
xaac-os configure-rustdesk-branding --dry-run --json
```
