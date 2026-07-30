# Fase 9.8 — Secure Boot i TPM

Aquesta fase tanca el Bloc 9 amb una decisió explícita i verificable per al Dell Wyse 3040.

## Decisió

* La cadena UEFI es prepara amb els paquets signats de Debian (`shim-signed`, `grub-efi-amd64-signed` i kernel signat).
* Secure Boot és **condicional**: no es força si el firmware de la unitat no exposa controls compatibles.
* TPM 2.0 és **opcional** i només es reserva per a attestació i segellat de secrets d’enrolament.
* TPM no és requisit d’arrencada, recuperació, factory reset ni administració local.
* No es generen ni distribueixen claus privades pròpies.

## Execució

```bash
xaac-os --root . configure-secure-boot-tpm --dry-run
xaac-os --root . configure-secure-boot-tpm
```

El probe instal·lat informa de l’estat observable de Secure Boot i de la presència d’un dispositiu TPM.
