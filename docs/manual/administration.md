# Guia d’administració

## Accés local
L’usuari final només utilitza `xaac-kiosk`. L’administració local es realitza amb `xaac-admin` des del TTY administratiu i amb canvi obligatori de la contrasenya inicial.

## SSH
OpenSSH està actiu per defecte perquè és el canal de gestió remota del terminal. Abans del provisionament central, `xaac-admin` pot autenticar-se amb contrasenya o amb una clau pública autoritzada; `root`, `xaac-kiosk` i els comptes de servei no poden iniciar sessió per SSH. Quan XAAC Management Server ha provisionat les claus a través de XAAC Thin Client Agent, la política de producció ha de desactivar l'autenticació per contrasenya i conservar només la clau pública.

## Idioma i teclat
Després de la instal·lació, useu `xaac-admin-change-language` i `xaac-admin-change-keyboard`. Ambdós proporcionen `get`, `list`, `set <valor>` i `--help`; `set` requereix `sudo`. La referència completa, els valors admesos i els efectes sobre les sessions es documenten en [Canvi d'idioma i distribució de teclat](../administration/localization.md).

## Manteniment i serveis
Useu `sudo xaac-maintenance status` i `sudo xaac-maintenance health` com a punt d'entrada normal. Per a una incidència, genereu `sudo xaac-maintenance diagnostics`; el bundle resultant està sanititzat i no incorpora secrets.

## Estat del dispositiu
La identitat, l’inventari, l’enrolament XMS i la política activa són persistents. No copieu aquests fitxers entre dispositius; per a clonació useu exclusivament el flux de sanejament de la imatge mestra.

## Operacions destructives
Factory reset, recuperació i reinstal·lació requereixen confirmació explícita, alimentació estable i registre d’auditoria.
