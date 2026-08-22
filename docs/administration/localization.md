# Canvi d'idioma i distribució de teclat

XAAC Thin Client OS proporciona dos scripts administratius no interactius per canviar la configuració regional després de la instal·lació. Estan pensats per a ús local, per SSH i per a una futura execució orquestrada per XAAC Management Server a través de XAAC Thin Client Agent. Idioma i teclat són configuracions independents.

## Idioma: `xaac-admin-change-language`

Sintaxi:

```bash
xaac-admin-change-language get
xaac-admin-change-language list
sudo xaac-admin-change-language set <valor>
xaac-admin-change-language --help
```

Valors admesos:

| Valor | Locale persistent |
| --- | --- |
| `ca` | `ca_ES.UTF-8` |
| `es` | `es_ES.UTF-8` |
| `en` | `en_US.UTF-8` |

`get` mostra el valor actual en forma curta; `list` mostra els valors acceptats; `set` valida el valor, comprova que el locale estiga disponible i actualitza de manera atòmica `/etc/default/locale` i `/etc/locale.conf`. Si existeix el sincronitzador de XAAC Thin Client, també actualitza la llengua configurada de l'aplicació.

Exemples:

```bash
xaac-admin-change-language get
xaac-admin-change-language list
sudo xaac-admin-change-language set es
sudo xaac-admin-change-language set ca
```

El procés actual i les aplicacions ja obertes conserven el locale amb què es van iniciar. Per garantir que tot el quiosc adopte el nou idioma, reinicieu la sessió gràfica o, preferentment, el sistema.

## Teclat: `xaac-admin-change-keyboard`

Sintaxi:

```bash
xaac-admin-change-keyboard get
xaac-admin-change-keyboard list
sudo xaac-admin-change-keyboard set <layout>
xaac-admin-change-keyboard --help
```

Distribucions admeses en la versió 1.0.0:

- `es` — espanyol;
- `us` — anglès dels Estats Units;
- `gb` — anglès del Regne Unit;
- `fr` — francès;
- `de` — alemany;
- `it` — italià;
- `pt` — portuguès.

`set` valida la distribució XKB i actualitza `/etc/default/keyboard` amb `XKBLAYOUT=<layout>`. Conserva el model i les opcions XKB existents, i reinicia la variant a buida per evitar una variant incompatible amb la nova distribució. Quan `setupcon` està disponible, intenta reaplicar el teclat de consola immediatament. La sessió Wayland/labwc llig `/etc/default/keyboard` en arrancar, de manera que el canvi gràfic s'aplica en la pròxima sessió.

Exemples:

```bash
xaac-admin-change-keyboard get
xaac-admin-change-keyboard list
sudo xaac-admin-change-keyboard set es
sudo xaac-admin-change-keyboard set us
```

Per garantir que consola, Wayland/labwc i totes les aplicacions utilitzen el mateix mapa, es recomana reiniciar el sistema després d'un `set`.

## Idioma i teclat són independents

Una configuració en català amb teclat espanyol és vàlida i habitual:

```bash
sudo xaac-admin-change-language set ca
sudo xaac-admin-change-keyboard set es
```

No cal reinstal·lar XAAC Thin Client OS per canviar cap dels dos valors. Les ordres `get`, `list` i `--help` es poden executar sense `sudo`; `set` requereix privilegis de root.
