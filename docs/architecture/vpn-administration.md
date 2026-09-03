# Administració de XAAC Thin Client VPN

## Eina administrativa

L'administrador no ha d'editar perfils OpenVPN ni extraure certificats manualment.
XAAC Thin Client OS instal·la:

```text
/usr/local/sbin/xaac-vpn-admin
```

L'eina s'executa amb `sudo` i concentra el provisionament del perfil, la política
administrativa, l'estat i l'eliminació segura.

## Provisionament del perfil

A partir dels dos fitxers exportats d'OPNsense:

```text
client.ovpn
client.p12
```

l'administrador executa únicament:

```sh
sudo xaac-vpn-admin provision client.ovpn client.p12
```

L'eina demana interactiuament la contrasenya del PKCS#12. La contrasenya no
s'inclou en la línia d'ordres ni es desa en cap fitxer persistent.

Internament, l'eina:

1. valida el PKCS#12;
2. treballa exclusivament en un directori privat temporal sota `/run`;
3. extrau temporalment CA, certificat i clau;
4. adapta el perfil a OpenVPN 3;
5. comprova que existeixen `auth-user-pass` i `static-challenge`;
6. quan OPNsense exporta `verify-x509-name ... subject`, conserva la verificació
   X.509 però la normalitza al CN del servidor amb el mode `name`;
7. importa primer un perfil candidat persistent i el valida;
8. comprova que el perfil importat ja no depén dels fitxers temporals;
9. substitueix de manera controlada el perfil definitiu `XAAC VPN`;
10. reinicia `xaac-vpn-manager`;
11. elimina el directori temporal i la clau privada extreta.

El perfil definitiu que consumeix XAAC Thin Client VPN s'anomena sempre:

```text
XAAC VPN
```

Reexecutar `provision` amb un nou parell `.ovpn/.p12` actualitza el perfil sense
necessitat d'eliminar-lo manualment abans.

## Política administrativa

`/etc/xaac/vpn-manager.toml` continua sent la font única de veritat. L'administrador
no necessita editar-lo directament; usa:

```sh
sudo xaac-vpn-admin policy disabled
sudo xaac-vpn-admin policy optional
sudo xaac-vpn-admin policy required
```

Semàntica:

- `disabled`: el component VPN no està disponible per a l'usuari; XAAC Thin Client Remote i el Dock continuen arrancant amb normalitat.
- `optional`: la VPN està disponible des del Dock i l'usuari pot connectar-la o continuar sense túnel. La seua GUI no s'obri automàticament en l'arranc.
- `required`: la VPN és obligatòria per a les connexions que depenguen d'ella, però no bloqueja l'arranc gràfic. XAAC Thin Client Remote i el Dock es mostren igualment perquè l'usuari puga obrir VPN des del Dock i corregir la situació.

L'actualització del fitxer és atòmica, manté `root:root 0644` i reinicia
`xaac-vpn-manager`. La política nova s'aplica completament en iniciar la pròxima
sessió de quiosc. En 1.1.0 la política VPN no s'utilitza com a `gate` del procés Remote: separa obligatorietat funcional d'arranc de la interfície.

### Política remota via XMS

XAAC Thin Client Agent reutilitza aquesta frontera, però de manera estrictament
limitada. XMS envia una política `system` signada amb `content_schema_revision = 2`
i una única secció VPN:

```json
{
  "vpn": {
    "mode": "required"
  }
}
```

El flux és `XMS → XAAC Agent → xaac-privileged-helper → xaac-vpn-admin policy`.
L'Agent i el helper només accepten `disabled`, `optional` o `required`. Una revisió
igual o anterior a la política activa es rebutja sense tornar a aplicar-la. Si el
mode arriba a canviar però falla la persistència de la nova política, l'Agent intenta
restaurar el mode anterior.

Aquesta interfície remota **no** admet `provision`, `remove`, `.ovpn`, `.p12`,
contrasenyes, OTP ni shell genèrica. El provisionament del perfil continua sent una
operació local de l'administrador.

## Estat

```sh
sudo xaac-vpn-admin status
```

Mostra:

- política administrativa;
- existència del perfil `XAAC VPN`;
- validesa del perfil;
- estat de `xaac-vpn-manager`;
- estat de la sessió VPN.

Per a consum de màquina, especialment per XAAC Agent:

```sh
sudo xaac-vpn-admin status --json
```

La resposta usa el contracte `xaac-vpn-status/v1` i conté únicament estat
administratiu. No inclou usuari VPN, contrasenya, OTP, claus, PKCS#12 ni contingut
del perfil OpenVPN.

## Desprovisionament

```sh
sudo xaac-vpn-admin remove
```

Elimina el perfil `XAAC VPN` i estableix automàticament `policy = "disabled"` per
evitar que una política `required` deixe el quiosc bloquejat sense perfil.

## DNS OpenVPN 3

XAAC Thin Client OS no usa `systemd-resolved`. El constructor inicialitza
OpenVPN 3 perquè use directament `/etc/resolv.conf`. Aquesta configuració és
necessària perquè els DNS rebuts per la VPN s'apliquen al túnel full-tunnel.

L'administrador no ha de modificar manualment `/var/lib/openvpn3/netcfg.json` ni
`/etc/resolv.conf`.

## Seguretat

- La GUI no necessita privilegis.
- Contrasenya VPN i OTP no es persisteixen.
- La contrasenya del PKCS#12 no es passa com a argument de procés.
- La clau privada extreta només existeix temporalment sota `/run`, amb permisos
  restrictius, durant el provisionament.
- El perfil definitiu és gestionat pel Configuration Manager d'OpenVPN 3.
- `/etc/xaac/vpn-manager.toml` no conté credencials d'usuari.
- El helper de XAAC Agent conserva `ProtectSystem=strict`; l’única excepció de configuració writable per a la política VPN és `/etc/xaac`.
- La interfície remota de l’Agent només permet consultar estat i canviar entre els tres modes de política; no permet provisionar ni eliminar perfils.

## Consoles TTY

El cursor continua ocult globalment durant l'arranc silenciós de tty1, però el
drop-in de `getty@.service` restaura explícitament el cursor a les consoles de
text autenticades.
