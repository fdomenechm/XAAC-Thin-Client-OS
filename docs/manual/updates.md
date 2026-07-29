# Guia d’actualització

## Canals i anells
Les actualitzacions avancen per laboratori, pilot i producció. No promocioneu un anell sense èxit, observació mínima i aprovació.

## Flux
1. Comprovació en el repositori APT XAAC o importació USB/XMS.
2. Descàrrega i staging amb control d’espai.
3. Verificació de signatura, hashes, arquitectura, perfil i dependències.
4. Punt de recuperació i instal·lació transaccional.
5. Validació de serveis i confirmació.

## Fallada i rollback
Una versió defectuosa queda bloquejada. El rollback restaura paquets, configuració i estat anterior, i deixa auditoria. No forceu una actualització quan la verificació falle.
