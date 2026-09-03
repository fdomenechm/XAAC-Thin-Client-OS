# Bloc 7.5 — Administració i enrolament segur de XAAC Agent

## Objectiu

Eliminar el provisionament manual d'`agent.ini` i del token XMS, i establir una
interfície administrativa única, segura i verificable per al cicle de vida de
XAAC Agent.

## Interfície

El paquet Debian `xaac-agent 1.0.0-5` incorpora `/usr/sbin/xaac-agent-admin` amb
les ordres `provision`, `enable`, `disable`, `status` i `unenroll`. L'OS valida
tant el launcher privat com l'enllaç administratiu abans de completar el rootfs.

El token només s'accepta de manera interactiva oculta, des d'un fitxer privat o
per stdin. No existeix cap argument `--token`. El fitxer bootstrap és temporal i
s'elimina després de l'intent d'enrolament.

## Contracte OS ↔ Agent

`config/xms-enrollment.yaml` descriu el contracte `xaac-agent-admin/v1`. Durant la
construcció de producció l'OS genera `/etc/xaac/xms-enrollment-manifest.json` i
verifica que no continga secrets. El cicle de vida real, les claus Ed25519, les
credencials persistents i l'estat de registre continuen sent propietat exclusiva
de XAAC Agent.

## Fallades i reenrolament

- Un bootstrap fallit deixa l'Agent desactivat i elimina el token temporal.
- `disable` conserva identitat i credencials.
- Un `unenroll` no confirmat per XMS restaura un servei que estava actiu.
- Un dispositiu `revoked` o `unenrolled` necessita `--reenroll` explícit.

## ISO

No es genera ISO en aquesta fase. Les proves d'integració de rootfs corresponen a
la fase 7.6 i la ISO consolidada a la fase 7.7.
