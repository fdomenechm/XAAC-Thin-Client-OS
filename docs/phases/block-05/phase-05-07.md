# Fase 5.7 — Control d’apagada i reinici

## Objectiu

Evitar que l’usuari de quiosc apague, reinicie, suspenga o hiberne el dispositiu directament, i canalitzar únicament les accions autoritzades a través de XAAC Agent.

## Implementació

- Política declarativa `config/power-action-control.yaml` amb denegació per defecte.
- Apagada i reinici disponibles només com a peticions confirmades a l’Agent.
- Suspensió i hibernació bloquejades.
- Tecles físiques d’energia, reinici, suspensió, hibernació i tapa ignorades per `systemd-logind`.
- Política Polkit que impedeix a `xaac-kiosk` invocar directament les accions de `login1`.
- Helper restringit que només accepta `poweroff` o `reboot`, aplica timeout i envia una petició al socket Unix de l’Agent.
- Protecció contra peticions duplicades, confirmacions accidentals i esperes indefinides.
- Recuperació basada primer en reiniciar la sessió; el reinici complet del dispositiu no és automàtic davant una fallada del supervisor.

## Ordre

```bash
xaac-os configure-power-action-control --dry-run
xaac-os configure-power-action-control
```

## Fitxers generats

- `/etc/systemd/logind.conf.d/40-xaac-power-control.conf`
- `/etc/polkit-1/rules.d/90-xaac-kiosk-power.rules`
- `/usr/local/libexec/xaac/request-power-action`
- `/etc/xaac/kiosk/power-action-control.json`

## Limitacions

El socket i el protocol definitius de XAAC Agent s’integraran al Bloc 6. En aquesta fase es fixa el contracte local i s’aplica un comportament fail-closed quan l’Agent no està disponible.
