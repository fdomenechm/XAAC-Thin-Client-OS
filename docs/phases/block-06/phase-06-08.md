# Fase 6.8 — Enrolament XMS

Aquesta fase tanca el Bloc 6 amb un model local, segur i auditable d’enrolament del dispositiu en XAAC Management Server.

## Objectius implementats

- token d’enrolament validat i mai persistit en clar;
- petició vinculada a la identitat persistent del dispositiu;
- estat pendent d’aprovació;
- instal·lació atòmica del certificat del dispositiu i de la CA d’XMS;
- renovació controlada de certificat;
- desenrolament amb eliminació de credencials;
- estat d’error segur sense exposició de secrets;
- operacions idempotents i protecció contra enllaços simbòlics.

## Configuració

El perfil es troba en `config/xms-enrollment.yaml`. L’URL de producció haurà de substituir el valor de mostra i sempre ha d’utilitzar HTTPS.

## CLI

```bash
xaac-os --root . configure-xms-enrollment
xaac-os --root . configure-xms-enrollment --dry-run
```

La CLI prepara el motor local. L’intercanvi HTTPS efectiu serà responsabilitat de XAAC Agent, que usarà aquesta màquina d’estats i els fitxers persistents.

## Estats

- `unenrolled`
- `pending_approval`
- `enrolled`
- `renewal_pending`
- `error`

## Persistència

- `/var/lib/xaac-agent/enrollment/state.json`
- `/var/lib/xaac-agent/enrollment/request.json`
- `/var/lib/xaac-agent/enrollment/device.crt`
- `/var/lib/xaac-agent/enrollment/xms-ca.crt`
- `/etc/xaac/xms-enrollment-manifest.json`
