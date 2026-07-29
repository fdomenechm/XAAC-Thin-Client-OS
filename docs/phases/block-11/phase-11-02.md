# Fase 11.2 — Recuperació de l'aplicació

Aquesta fase defineix la recuperació escalonada de XAAC Thin Client i de la sessió de quiosc.

El flux autoritzat és: recopilar diagnòstic, reiniciar el client, reiniciar la sessió quan el client no es recupera, netejar exclusivament estat efímer i, si la fallada està associada a una política, restaurar l'última política anterior validada.

La identitat del dispositiu, l'enrolament i la política activa no poden eliminar-se durant la neteja. El rollback exigeix validació de signatura i esquema i substitució atòmica. Qualsevol fallada es resol en mode *fail-closed*, conserva evidències i notifica XAAC Agent i XMS. El `factory reset` automàtic continua prohibit.

## Ordre

```bash
xaac-os --root . configure-application-recovery --dry-run
xaac-os --root . configure-application-recovery
```
