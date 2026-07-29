# Fase 12.5 — Clonació massiva

Aquesta fase prepara una imatge mestra reproduïble per desplegar múltiples Dell Wyse 3040 sense duplicar identitats.

## Flux

1. Verificar el SHA-256 de la imatge mestra.
2. Muntar el sistema arrel fora de línia i eliminar `machine-id`, claus SSH, identitat XAAC, enrolament XMS, logs i llavor aleatòria.
3. Marcar el primer inici perquè cada clon regenere identificadors únics.
4. Escriure la imatge únicament sobre dispositius explícits després de la frase `CLONE XAAC`.
5. Rebutjar destinacions muntades i verificar cada còpia byte a byte.
6. Validar GPT i les etiquetes `XAAC_EFI`, `XAAC_ROOT`, `XAAC_DATA` i `XAAC_RECOVERY`.

La preparació no executa operacions destructives. Genera scripts auditable en `.build/cloning/`.
