# Bloc 7.4 — Política VPN remota

## Objectiu

Integrar la política administrativa de XAAC Thin Client VPN amb XMS sense convertir
XAAC Agent en gestor de credencials o de material criptogràfic VPN.

## Flux autoritzat

```text
XMS
  │ política system signada, content schema v2
  ▼
XAAC Agent
  │ operació tipada
  ▼
xaac-privileged-helper
  │ /usr/local/sbin/xaac-vpn-admin policy <mode>
  ▼
/etc/xaac/vpn-manager.toml
```

Els únics modes admesos són `disabled`, `optional` i `required`. XAAC Agent
publica les capacitats `vpn-policy-v1` i `vpn-status-v1`.

## Estat de màquina

`xaac-vpn-admin status --json` retorna `xaac-vpn-status/v1` amb la política,
l'existència/validesa del perfil, l'estat del manager i si hi ha sessió connectada.
El contracte no conté usuari, contrasenya, OTP, claus ni contingut de certificats.

## Frontera de seguretat

- El helper només admet `vpn-policy` i `vpn-status`.
- No admet `provision`, `remove`, shell, `.ovpn` o `.p12` des de l'Agent.
- `ProtectSystem=strict` es conserva i l'única excepció d'escriptura de configuració
  és `/etc/xaac`.
- La revisió de política ha de ser estrictament superior a l'activa.
- Si el mode VPN canvia però falla la persistència de la política activa, s'intenta
  restaurar el mode anterior.

## Empaquetatge

La revisió Debian de l'Agent és `1.0.0-4`; la versió de l'aplicació continua sent
`1.0.0`. L'OS valida versió, arquitectura, dependències i SHA-256 de l'artefacte
abans d'incloure'l en una ISO.

## ISO

No es genera ISO en aquesta fase. La validació real sobre el Dell Wyse 3040 queda
reservada per a la fase final consolidada del Bloc 7.
