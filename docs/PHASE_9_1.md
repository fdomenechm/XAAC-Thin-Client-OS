# Fase 9.1 — Política de seguretat base

## Objectiu

Establir el marc de seguretat comú de XAAC Thin Client OS abans d'aplicar els controls tècnics específics del Bloc 9.

## Implementació

El perfil `config/security-policy.yaml` defineix de manera declarativa i versionada:

- els objectius de confidencialitat, integritat, disponibilitat i responsabilitat;
- els actius protegits i la seua criticitat;
- els actors i el nivell de confiança;
- les superfícies d'atac locals, de xarxa, suport remot, cadena de subministrament i accés físic;
- les amenaces amb probabilitat, impacte, controls i risc residual;
- el catàleg de controls, propietaris i fases responsables;
- els riscos explícitament acceptats, amb justificació, responsable i revisió prevista.

La implementació valida totes les referències creuades i genera tres artefactes:

- `/etc/xaac/security/base-policy.json`: política operativa sense detalls de risc acceptat;
- `/usr/share/doc/xaac-thin-client-os/security-threat-model.json`: model d'amenaces i riscos acceptats;
- `/var/lib/xaac-agent/security/base-policy-state.json`: estat resumit i versionat per a XAAC Agent.

## Ordres

```bash
xaac-os --root . configure-security-policy --dry-run
xaac-os --root . configure-security-policy
```

## Garanties

- validació estricta de l'esquema i dels identificadors;
- referències obligatòries entre amenaces, actius, actors, superfícies i controls;
- rutes absolutes i confinades al `rootfs`;
- protecció davant enllaços simbòlics;
- escriptura atòmica, idempotent i amb permisos `0640` o `0644` segons sensibilitat;
- separació entre política operativa, model documental i estat de l'Agent.

## Limitacions

Aquesta fase defineix i instal·la la línia base, però no aplica encara tots els controls anunciats. Els privilegis d'usuaris, el hardening de systemd, AppArmor, kernel, integritat, signatures i Secure Boot/TPM es desenvolupen en les fases 9.2 a 9.8.
