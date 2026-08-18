# Guia d’administració

## Accés local
L’usuari final només utilitza `xaac-kiosk`. L’administració local es realitza amb `xaac-admin` des del TTY administratiu i amb canvi obligatori de la contrasenya inicial.

## SSH
OpenSSH ha d’estar restringit a usuaris, claus i adreces IP autoritzades. No s’admet autenticació SSH del compte de quiosc ni accés permanent no justificat.

## Manteniment i serveis
Useu `sudo xaac-maintenance status` i `sudo xaac-maintenance health` com a punt d'entrada normal. Per a una incidència, genereu `sudo xaac-maintenance diagnostics`; el bundle resultant està sanititzat i no incorpora secrets.

## Estat del dispositiu
La identitat, l’inventari, l’enrolament XMS i la política activa són persistents. No copieu aquests fitxers entre dispositius; per a clonació useu exclusivament el flux de sanejament de la imatge mestra.

## Operacions destructives
Factory reset, recuperació i reinstal·lació requereixen confirmació explícita, alimentació estable i registre d’auditoria.
