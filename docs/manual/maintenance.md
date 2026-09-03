# Guia de manteniment i diagnòstic

La interfície administrativa canònica és `xaac-maintenance` i s'executa amb `sudo`.

```bash
sudo xaac-maintenance status
sudo xaac-maintenance health
sudo xaac-maintenance network
sudo xaac-maintenance storage
sudo xaac-maintenance services
sudo xaac-maintenance logs
sudo xaac-maintenance cleanup
sudo xaac-maintenance diagnostics
```

## Diagnòstic per a suport

`diagnostics` crea un bundle root-only sota `/var/lib/xaac-maintenance/diagnostics/` i imprimeix la ruta final. Copieu únicament eixe `.tar.gz` quan calga facilitar evidències a suport.

El bundle no incorpora el contingut de perfils NetworkManager, secrets XAAC, token d'enrolament de l'Agent, claus privades SSH ni cache de rollback. Els logs i estats textuals són sanititzats per eliminar contrasenyes, tokens, OTP, secrets, credencials URL i claus privades.

## Neteja

`cleanup` manté una política conservadora: retenció del journal, `apt-get clean` i eliminació de bundles de diagnòstic antics. No elimina configuració ni punts de rollback.
