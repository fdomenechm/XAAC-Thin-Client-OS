# Fase 11.3 — Reparació de paquets

Aquesta fase incorpora una política declarativa i *fail-closed* per comprovar i reparar paquets del sistema sense substituir la instal·lació completa.

## Flux de reparació

1. Executar `dpkg --audit` i `apt-get check`.
2. Verificar els fitxers dels paquets XAAC gestionats.
3. Reinstal·lar únicament els paquets afectats des de repositoris signats.
4. Reparar dependències de manera controlada.
5. Restaurar configuració des d'una còpia validada i conservar les personalitzacions locals autoritzades.
6. Executar totes les comprovacions finals abans de confirmar l'èxit.
7. Conservar diagnòstics i notificar XAAC Agent i XMS.

La identitat, l'enrolament i la política activa estan protegits. El procés no pot executar un `factory reset` automàtic.

```bash
xaac-os --root . configure-package-repair --dry-run
xaac-os --root . configure-package-repair
```
