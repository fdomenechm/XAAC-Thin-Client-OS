# Administració i enrolament de XAAC Agent

## Propietat del cicle de vida

XAAC Thin Client OS incorpora XAAC Agent com a paquet Debian, però no gestiona
manualment les seues credencials. La interfície administrativa suportada és
`/usr/sbin/xaac-agent-admin`, propietat del paquet `xaac-agent`.

L'OS instal·la `/etc/xaac/xms-enrollment-manifest.json` com a contracte local
`xaac-agent-admin/v1`. Aquest manifest no conté secrets i declara únicament les
rutes, ordres i propietats necessàries per validar la integració.

## Provisionament inicial

L'administrador executa:

```sh
sudo xaac-agent-admin provision --server-url https://xms.example.org
```

El token d'enrolament es demana de manera oculta. Per a automatització controlada
també es pot llegir des d'un fitxer privat o de l'entrada estàndard:

```sh
sudo xaac-agent-admin provision --server-url https://xms.example.org --token-file /ruta/privada/token
sudo xaac-agent-admin provision --server-url https://xms.example.org --token-stdin
```

No existeix `--token`: el secret no es transporta en la línia d'ordres. El token
és temporal, s'instal·la amb permisos restrictius només durant el bootstrap i
s'elimina tant si l'enrolament acaba correctament com si falla. Després, l'Agent
utilitza la credencial persistent emesa per XMS.

## Cicle de vida

```sh
sudo xaac-agent-admin status
sudo xaac-agent-admin status --json
sudo xaac-agent-admin enable
sudo xaac-agent-admin disable
sudo xaac-agent-admin unenroll --reason "retirada del dispositiu"
```

`disable` para l'Agent però conserva la identitat i les credencials per poder-lo
reactivar. `unenroll` demana la baixa a XMS mitjançant el procés no privilegiat de
l'Agent i només elimina la credencial persistent quan el protocol ho confirma. Si
la baixa remota falla, un servei que estava actiu es restaura sense modificar la
configuració ni les credencials.

Un dispositiu marcat localment com `revoked` o `unenrolled` requereix una decisió
administrativa explícita per tornar a enrolar-lo:

```sh
sudo xaac-agent-admin provision --server-url https://xms.example.org --reenroll
```

## Frontera de seguretat

- `xaac-agent-admin` només es pot executar com root.
- L'Agent principal continua executant-se com `xaac-agent`.
- `xaac-agent-admin` no exposa credencials persistents en `status --json`.
- El token bootstrap no forma part de la imatge, del manifest de l'OS ni dels
  arguments de procés.
- La ruta persistent del token temporal es deriva de `agent.ini`.
- La credencial systemd de bootstrap és opcional després de l'enrolament.
- Les operacions VPN continuen separades en `xaac-vpn-admin`; l'enrolament de
  l'Agent no pot provisionar `.ovpn`, `.p12`, contrasenyes ni OTP.
