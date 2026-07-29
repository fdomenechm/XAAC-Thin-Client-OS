# Fase 1.7 — Sistema de hooks

El constructor disposa de sis punts d'extensió ordenats:

1. `pre-bootstrap`
2. `post-bootstrap`
3. `pre-packages`
4. `post-packages`
5. `pre-image`
6. `post-image`

Els hooks es desen en `hooks/<fase>/`, han de ser fitxers regulars executables i
s'executen en ordre lexicogràfic. Els directoris buits són vàlids i els fitxers
ocults s'ignoren.

Cada hook rep les variables `XAAC_HOOK_PHASE`, `XAAC_PROJECT_ROOT`,
`XAAC_BUILD_ID`, `XAAC_WORKSPACE`, `XAAC_RENDERED_DIR`, `XAAC_ARTIFACTS_DIR` i
`XAAC_TMP_DIR`. L'eixida estàndard i d'error queda registrada en
`.build/runs/<id>/logs/hooks/<fase>/<hook>.log`.

Un codi d'eixida diferent de zero, un timeout o un hook sense permisos
interromp la construcció de manera segura.
