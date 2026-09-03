# Bloc 7 — Fase 7.1: consolidació del paquet XAAC Thin Client Agent

## Objectiu

Establir una única frontera d'instal·lació entre XAAC Thin Client OS i XAAC
Thin Client Agent abans d'abordar IPC, política VPN i enrolament XMS.

## Decisions

- Versió de l'aplicació Agent: `1.0.0`.
- Versió del paquet Debian: `1.0.0-1`.
- Artefacte obligatori: `packages/xaac-agent_1.0.0-1_amd64.deb`.
- El `.deb` és l'únic propietari del runtime, configuració, usuari i unitats
  systemd de l'Agent.
- XAAC Thin Client OS només valida, instal·la i comprova el resultat.
- El constructor de producció falla abans de generar la ISO si el paquet és un
  placeholder, la versió o arquitectura no coincideixen, falten dependències o
  el SHA-256 és diferent.

## Runtime

Des de la versió 1.1.0, el paquet utilitza Python 3.13 del sistema Debian i no
modifica `/usr/bin/python3`. La configuració real és `/etc/xaac-agent/agent.ini`.
Les unitats de paquet són `xaac-agent.service` i
`xaac-privileged-helper.socket`.

## Resultat

La fase deixa preparada la base per a les fases següents del Bloc 7 sense
introduir encara el nou contracte IPC ni la gestió remota de la política VPN.
