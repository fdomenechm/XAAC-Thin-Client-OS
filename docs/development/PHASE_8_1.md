# Fase 8.1 — Paquet RustDesk XAAC

## Objectiu

Integrar de manera declarativa i auditable un paquet Debian controlat de RustDesk, sense incorporar encara branding, servei permanent, configuració de servidors ni activació remota.

## Implementació

- Perfil `config/rustdesk-package.yaml` amb origen, llicència, URL del codi font, versió, arquitectura i dependències.
- Paquet esperat `rustdesk-xaac_1.0.0_amd64.deb`, verificat amb `dpkg-deb` abans de qualsevol canvi.
- Validació estricta del nom, versió, arquitectura, dependències i SHA-256 opcional.
- Còpia atòmica al cache intern del rootfs i manifest auditable en `/etc/xaac/rustdesk/package.json`.
- Instal·lació mínima amb `dpkg` i reparació de dependències sense paquets recomanats.
- Desinstal·lació completa mitjançant `apt-get purge`, `autoremove` i retirada del cache i manifest.
- Ordres CLI `install-rustdesk` i `uninstall-rustdesk`, amb suport `--dry-run`.
- Protecció contra rootfs insegurs, artefactes fora del projecte i enllaços simbòlics.

## Proves

Les proves cobreixen càrrega del perfil, origen controlat, metadades, dependències, planificació, dry-run, instal·lació, desinstal·lació, protecció de symlinks i exposició CLI.

## Limitacions deliberades

El `.deb` real no s'inclou en aquesta fase perquè no s'ha proporcionat encara el binari personalitzat. El perfil fixa el contracte que haurà de complir. Branding, servidor, servei systemd, activació sota demanda, consentiment i auditoria corresponen a les fases 8.2–8.8.
