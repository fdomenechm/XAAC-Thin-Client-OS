# Fase 11.1 — Model d'estats de recuperació

Aquesta fase estableix el contracte declaratiu de recuperació de XAAC Thin Client OS. El model identifica les fallades d'aplicació, sessió, actualització i integritat, les comptabilitza dins de finestres temporals i selecciona sempre l'estat més greu que corresponga.

## Estats

- `healthy`: funcionament normal i comptadors transitoris nets.
- `degraded`: primera degradació; es recullen diagnòstics i es notifica l'Agent.
- `recovering`: s'executa una acció de recuperació controlada.
- `safe`: es bloquegen fluxos insegurs, es conserven evidències i es notifica Agent i XMS.
- `manual_intervention`: s'atura la recuperació automàtica fins a intervenció autoritzada.

Els llindars són estrictament creixents i la classificació és determinista. Una fallada d'una classe no pot ocultar una fallada més greu d'una altra classe.

## Seguretat

El model és *fail-closed*, prohibeix el `factory reset` automàtic, exigeix confirmació per a accions destructives i conserva evidències. La política efectiva s'instal·la amb permisos `0644` i l'estat mutable amb `0640`, mitjançant escriptures atòmiques i rebutjant destinacions simbòliques.

## Ús

```bash
xaac-os --root . configure-recovery-model --dry-run
xaac-os --root . configure-recovery-model
```

La fase només defineix i instal·la el model. Les accions concretes de recuperació de l'aplicació s'implementaran en la fase 11.2.
