# Guia de seguretat

## Principis
Mínim privilegi, separació de comptes, configuració fail-closed, artefactes signats i traçabilitat.

## Comptes
`root` queda reservat; `xaac-admin` administra; `xaac-kiosk` i `xaac-agent` no disposen de login interactiu.

## Serveis
Manteniu el hardening systemd, AppArmor, sysctl, nftables i les restriccions de dispositius. Qualsevol relaxació ha de quedar documentada i revisada.

## Secrets i claus
No inclogueu claus privades, tokens, credencials ni certificats particulars en el ZIP, ISO o imatge mestra. Les claus de dispositiu es generen al primer inici.

## Integritat
Verifiqueu manifests, hashes i signatures abans d’instal·lar paquets, actualitzacions, recuperacions o imatges. Investigueu qualsevol divergència abans de reparar-la.
