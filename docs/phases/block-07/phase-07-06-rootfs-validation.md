# Bloc 7.6 — Validació integrada del rootfs

La fase 7.6 valida conjuntament XAAC Thin Client OS i el paquet Debian real de XAAC Agent abans de generar cap ISO.

## Gate de font i paquet

`./scripts/validate-block7-integration.sh` extrau `xaac-agent_1.0.0-6_amd64.deb` i comprova identitat i SHA-256, frontera systemd, helper privilegiat, cicle d’enrolament, contracte local, grups del quiosc, XMS i política VPN.

## Gate del rootfs de producció

El constructor executa una verificació final al final de `configure` i de nou abans de `squashfs`. Es comproven paquets, usuaris i grups, permisos direccionals, unitats systemd, absència del token bootstrap, `xaac-agent-admin`, manifests locals/XMS i el contracte `xaac-vpn-status/v1`.

La imatge base no arranca l’Agent abans de l’enrolament: `xaac-agent.service` ha d’estar deshabilitat i `xaac-privileged-helper.socket` habilitat.

No es genera ISO en aquesta fase.
