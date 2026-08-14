# Fase 6.2 — Paquet XAAC Agent (històrica)

Aquesta fase va introduir la primera integració de XAAC Agent. La implementació
original ha estat **substituïda en el Bloc 7, Fase 7.1** per la integració basada
exclusivament en el paquet Debian real.

L'estat vigent és:

- paquet `xaac-agent_1.0.0-1_amd64.deb`;
- configuració `/etc/xaac-agent/agent.ini`;
- runtime privat `/opt/xaac-agent/runtime`;
- usuari i unitats systemd creats pel mateix `.deb`;
- XAAC Thin Client OS només valida, instal·la i verifica el paquet;
- el constructor de producció rebutja placeholders, versions, arquitectura,
  dependències o SHA-256 incorrectes.

Vegeu `docs/phases/block-07/phase-07-01-agent-integration.md`.
