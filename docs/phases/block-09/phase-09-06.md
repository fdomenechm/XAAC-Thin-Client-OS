# Fase 9.6 — Integritat de fitxers

## Objectiu

Detectar canvis no autoritzats en fitxers crítics i proporcionar una reparació local controlada.

## Implementació

- Manifest determinista amb SHA-256, mida i ruta absoluta lògica.
- Baseline local en `/var/lib/xaac-integrity/baseline`.
- Verificador executable en `/usr/local/libexec/xaac/verify-file-integrity`.
- Servei `xaac-file-integrity.service` i temporitzador horari.
- Estat per a XAAC Agent en `/var/lib/xaac-agent/security/file-integrity.json`.
- Exclusions explícites per a artefactes temporals.
- Reparació sota ordre explícita; mai automàtica durant la verificació ordinària.

## Limitacions

La baseline s'ha de regenerar després d'una actualització legítima. La protecció criptogràfica externa del manifest i dels paquets correspon a les fases 9.7 i 10.
