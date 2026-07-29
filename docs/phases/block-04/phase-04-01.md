# Fase 4.1 — Pila gràfica mínima

## Objectiu

Preparar una base gràfica mínima per a la futura sessió dedicada de XAAC Thin Client, prioritzant Wayland i mantenint X11 com a alternativa controlada.

## Implementació

- Perfil declaratiu `config/graphical-stack.yaml`.
- Wayland com a backend GTK principal i X11 com a fallback explícit.
- Paquets mínims de Wayland, X11, Mesa, GTK 4, libinput, xkbcommon, Fontconfig i fonts Roboto, Noto i DejaVu.
- Exclusió explícita d'escriptoris complets i shells convencionals.
- Generació atòmica de `/etc/xaac/session/graphical-stack.env`.
- Roboto com a família tipogràfica principal i predeterminada del sistema.
- Noto Sans i DejaVu Sans com a alternatives ordenades de reserva.
- Configuració global de Fontconfig en `/etc/fonts/conf.d/60-xaac-default-fonts.conf`.
- Configuració global de GTK 4 en `/etc/gtk-4.0/settings.ini` amb `gtk-font-name=Roboto 10`.
- Model de validació per a backend, display, GTK 4, renderer Mesa, resolució, teclat i ratolí.
- Proteccions contra rootfs insegurs, rutes insegures i enllaços simbòlics.

## Proves

La suite consolidada arriba a 485 proves. S'han afegit proves positives, negatives, de fallback X11, resolució, dispositius d'entrada, idempotència, seguretat de rutes i validació del perfil.

## Limitacions

Aquesta fase no selecciona ni inicia encara un compositor. Això correspon a la fase 4.2. La comprovació de renderització GTK real sobre maquinari o VM queda preparada pel model, però s'ha de validar en proves d'imatge amb una sessió gràfica activa.
