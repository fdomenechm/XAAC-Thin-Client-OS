# Fase 12.6 — Proves automatitzades d’imatge

Aquesta fase incorpora una suite declarativa per validar una imatge de producció ja arrencada. La política `config/image-tests.yaml` cobreix les huit àrees exigides pel calendari: arrencada, serveis, particions, usuaris, paquets, seguretat, actualització i recuperació.

L’ordre `xaac-os build-image-tests` genera un manifest determinista, un executor *fail-closed* i un esquema JSON per al resultat. L’executor continua després d’una fallada per recollir totes les evidències, retorna un codi diferent de zero si alguna comprovació falla i deixa un informe estructurat.

Les comprovacions que necessiten una màquina virtual o una imatge real es preparen, però no s’executen durant la suite unitària ordinària.
