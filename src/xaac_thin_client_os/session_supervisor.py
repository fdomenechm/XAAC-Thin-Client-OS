"""Session supervision configuration for XAAC Thin Client."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class SessionSupervisorError(RuntimeError):
    """Raised for invalid or unsafe session supervisor configuration."""


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise SessionSupervisorError(f"Ruta insegura: {name}")
    return path


def load_session_supervisor_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SessionSupervisorError(f"No s'ha pogut carregar el perfil: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 2:
        raise SessionSupervisorError("Perfil de supervisió invàlid o esquema no suportat")
    for section in ("supervision", "visual_handoff", "visual_session", "visual_recovery", "visual_power", "packages", "files"):
        if not isinstance(raw.get(section), dict):
            raise SessionSupervisorError(f"Secció obligatòria absent: {section}")
    cfg = raw["supervision"]
    expected_keys = {
        "user", "client_command", "supervisor_command", "error_screen_command", "startup_screen_command",
        "startup_screen_minimum_seconds", "startup_screen_timeout_seconds", "max_restarts",
        "restart_window_seconds", "initial_backoff_seconds", "maximum_backoff_seconds", "reset_after_seconds",
        "status_file", "shared_state_file", "event_directory", "thin_client_package",
        "state_heartbeat_seconds", "max_events", "voluntary_exit_codes",
    }
    if set(cfg) != expected_keys:
        raise SessionSupervisorError("Configuració del supervisor incompleta")
    if cfg.get("user") != "xaac-kiosk" or cfg.get("thin_client_package") != "xaac-thinclient":
        raise SessionSupervisorError("La supervisió ha d'usar xaac-kiosk i xaac-thinclient")
    for key in (
        "client_command", "supervisor_command", "error_screen_command", "startup_screen_command",
        "status_file", "shared_state_file", "event_directory",
    ):
        _safe_absolute(cfg.get(key), key)
    if cfg["shared_state_file"] != "/var/lib/xaac/thin-client/state/state.json":
        raise SessionSupervisorError("Ruta d'estat compartit incompatible")
    if cfg["event_directory"] != "/run/xaac/thin-client/events":
        raise SessionSupervisorError("Ruta d'events compartits incompatible")
    for key in (
        "max_restarts", "restart_window_seconds", "initial_backoff_seconds", "maximum_backoff_seconds",
        "reset_after_seconds", "startup_screen_minimum_seconds", "startup_screen_timeout_seconds",
        "state_heartbeat_seconds", "max_events",
    ):
        if not isinstance(cfg.get(key), int) or cfg[key] <= 0:
            raise SessionSupervisorError(f"Valor de supervisió invàlid: {key}")
    if cfg["initial_backoff_seconds"] > cfg["maximum_backoff_seconds"] or cfg["max_restarts"] > 20:
        raise SessionSupervisorError("Política de reinici insegura")
    if cfg["startup_screen_minimum_seconds"] > cfg["startup_screen_timeout_seconds"]:
        raise SessionSupervisorError("Temporització de pantalla d'espera invàlida")
    if not 5 <= cfg["state_heartbeat_seconds"] <= 300 or not 1 <= cfg["max_events"] <= 4096:
        raise SessionSupervisorError("Límits del contracte local invàlids")
    codes = cfg.get("voluntary_exit_codes")
    if not isinstance(codes, list) or not codes or any(not isinstance(code, int) or code < 0 or code > 255 for code in codes):
        raise SessionSupervisorError("Codis d'eixida voluntària invàlids")
    visual = raw["visual_handoff"]
    if set(visual) != {"background_color", "background_image", "background_command", "ready_timeout_seconds", "use_layer_shell"}:
        raise SessionSupervisorError("Contracte visual de transició incomplet")
    if visual.get("background_color") != "#383e42" or visual.get("use_layer_shell") is not True:
        raise SessionSupervisorError("La transició visual XAAC ha d'usar fons antracita i layer-shell")
    _safe_absolute(visual.get("background_image"), "background_image")
    _safe_absolute(visual.get("background_command"), "background_command")
    ready_timeout = visual.get("ready_timeout_seconds")
    if not isinstance(ready_timeout, int) or not 1 <= ready_timeout <= 15:
        raise SessionSupervisorError("Timeout de transició visual invàlid")
    session_visual = raw["visual_session"]
    session_visual_keys = {
        "stable_background_color", "cursor_theme", "cursor_size",
        "busy_cursor_name", "normal_cursor_name",
        "interactive_window_timeout_seconds", "thin_client_app_id", "vpn_app_id",
    }
    if set(session_visual) != session_visual_keys:
        raise SessionSupervisorError("Contracte visual de sessió incomplet")
    stable_background = session_visual.get("stable_background_color")
    if not isinstance(stable_background, str) or not stable_background.startswith("#") or len(stable_background) != 7:
        raise SessionSupervisorError("Fons estable de sessió invàlid")
    if stable_background.lower() in {"#000000", "#ffffff"}:
        raise SessionSupervisorError("El fons estable no pot ser negre ni blanc")
    if session_visual.get("cursor_theme") != "Adwaita":
        raise SessionSupervisorError("El cursor del quiosc ha d'usar el tema Adwaita")
    cursor_size = session_visual.get("cursor_size")
    if not isinstance(cursor_size, int) or not 16 <= cursor_size <= 48:
        raise SessionSupervisorError("Mida de cursor invàlida")
    if session_visual.get("busy_cursor_name") != "wait" or session_visual.get("normal_cursor_name") != "default":
        raise SessionSupervisorError("Noms de cursor de sessió invàlids")
    interactive_timeout = session_visual.get("interactive_window_timeout_seconds")
    if not isinstance(interactive_timeout, int) or not 2 <= interactive_timeout <= 60:
        raise SessionSupervisorError("Timeout de finestra interactiva invàlid")
    for key in ("thin_client_app_id", "vpn_app_id"):
        value = session_visual.get(key)
        if not isinstance(value, str) or not value.strip() or any(ch.isspace() for ch in value):
            raise SessionSupervisorError(f"App-id visual invàlid: {key}")
    recovery = raw["visual_recovery"]
    recovery_keys = {
        "background_color", "background_image", "use_layer_shell",
        "recovery_title", "recovery_message", "failure_title",
        "failure_message", "incident_prefix",
    }
    if set(recovery) != recovery_keys:
        raise SessionSupervisorError("Contracte visual de recuperació incomplet")
    if recovery.get("background_color") != "#ffffff" or recovery.get("use_layer_shell") is not True:
        raise SessionSupervisorError("La recuperació visual XAAC ha d'usar fons blanc i layer-shell")
    _safe_absolute(recovery.get("background_image"), "visual_recovery.background_image")
    for key in ("recovery_title", "recovery_message", "failure_title", "failure_message", "incident_prefix"):
        value = recovery.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 160:
            raise SessionSupervisorError(f"Text de recuperació invàlid: {key}")
    power = raw["visual_power"]
    power_keys = {
        "background_color", "background_image", "use_layer_shell", "ready_timeout_seconds",
        "poweroff_title", "poweroff_message", "reboot_title", "reboot_message",
    }
    if set(power) != power_keys:
        raise SessionSupervisorError("Contracte visual d'energia incomplet")
    if power.get("background_color") != "#ffffff" or power.get("use_layer_shell") is not True:
        raise SessionSupervisorError("La transició d'energia XAAC ha d'usar fons blanc i layer-shell")
    _safe_absolute(power.get("background_image"), "visual_power.background_image")
    power_ready_timeout = power.get("ready_timeout_seconds")
    if not isinstance(power_ready_timeout, int) or not 1 <= power_ready_timeout <= 5:
        raise SessionSupervisorError("Timeout de transició d'energia invàlid")
    for key in ("poweroff_title", "poweroff_message", "reboot_title", "reboot_message"):
        value = power.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 160:
            raise SessionSupervisorError(f"Text de transició d'energia invàlid: {key}")
    required = raw["packages"].get("required")
    visual_packages = {"gir1.2-gtk4layershell-1.0", "libgtk4-layer-shell0", "swaybg", "wlrctl"}
    if not isinstance(required, list) or not ({"python3.13", "python3-gi", "gir1.2-gtk-4.0"} | visual_packages) <= set(required):
        raise SessionSupervisorError("Dependències obligatòries incompletes")
    for name, value in raw["files"].items():
        _safe_absolute(value, name)
    return raw


@dataclass(frozen=True, slots=True)
class SessionSupervisorPlan:
    rootfs: Path
    packages: tuple[str, ...]
    files: tuple[tuple[PurePosixPath, str, int], ...]

    def to_manifest(self) -> dict[str, object]:
        return {"packages": list(self.packages), "files": [str(path) for path, _, _ in self.files]}


def create_session_supervisor_plan(rootfs: Path, profile_path: Path) -> SessionSupervisorPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise SessionSupervisorError(f"Rootfs insegur: {root}")
    profile = load_session_supervisor_profile(profile_path)
    cfg = profile["supervision"]
    visual = profile["visual_handoff"]
    session_visual = profile["visual_session"]
    recovery = profile["visual_recovery"]
    power = profile["visual_power"]
    files = profile["files"]
    voluntary = " ".join(str(code) for code in cfg["voluntary_exit_codes"])
    status_name = PurePosixPath(str(cfg["status_file"])).name
    supervisor = f'''#!/bin/sh
set -u
CLIENT={cfg["client_command"]}
ERROR_SCREEN={cfg["error_screen_command"]}
STARTUP_SCREEN={cfg["startup_screen_command"]}
STARTUP_MIN={cfg["startup_screen_minimum_seconds"]}
STARTUP_TIMEOUT={cfg["startup_screen_timeout_seconds"]}
STARTUP_READY_TIMEOUT={visual["ready_timeout_seconds"]}
BACKGROUND_COMMAND={visual["background_command"]}
STABLE_BACKGROUND={session_visual["stable_background_color"]}
INTERACTIVE_TIMEOUT={session_visual["interactive_window_timeout_seconds"]}
THIN_CLIENT_APP_ID={session_visual["thin_client_app_id"]}
VPN_APP_ID={session_visual["vpn_app_id"]}
STATUS_NAME={status_name}
RUNTIME_DIR=${{XDG_RUNTIME_DIR:-/run/user/$(id -u)}}
HANDOFF_BG_PID="$RUNTIME_DIR/xaac-handoff-background.pid"
STABLE_BG_PID="$RUNTIME_DIR/xaac-stable-background.pid"
STATUS="$RUNTIME_DIR/$STATUS_NAME"
STARTUP_READY="$RUNTIME_DIR/xaac-startup-screen.ready"
SHARED_STATE={cfg["shared_state_file"]}
EVENT_DIR={cfg["event_directory"]}
THIN_CLIENT_PACKAGE={cfg["thin_client_package"]}
HEARTBEAT_SECONDS={cfg["state_heartbeat_seconds"]}
MAX_EVENTS={cfg["max_events"]}
MAX_RESTARTS={cfg["max_restarts"]}
WINDOW={cfg["restart_window_seconds"]}
BACKOFF={cfg["initial_backoff_seconds"]}
MAX_BACKOFF={cfg["maximum_backoff_seconds"]}
RESET_AFTER={cfg["reset_after_seconds"]}
VOLUNTARY=" {voluntary} "
EVENT_SEQUENCE=0

iso_now() {{
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}}

thin_client_version() {{
  /usr/bin/dpkg-query -W -f='${{Version}}' "$THIN_CLIENT_PACKAGE" 2>/dev/null || printf '1.0.0'
}}

write_status() {{
  state=$1; code=${{2:-0}}; attempts=${{3:-0}}
  umask 077
  mkdir -p "$(dirname "$STATUS")"
  printf '{{"state":"%s","exit_code":%s,"restart_attempts":%s,"timestamp":%s}}\n' "$state" "$code" "$attempts" "$(date +%s)" > "$STATUS.tmp"
  mv "$STATUS.tmp" "$STATUS"
}}

write_shared_state() {{
  state=$1; code=${{2:-0}}; attempts=${{3:-0}}
  now=$(iso_now)
  version=$(thin_client_version)
  supervisor_state=active
  graphical_state=active
  health=healthy
  reasons='[]'
  last_error='null'
  case "$state" in
    starting)
      graphical_state=connecting
      ;;
    running)
      ;;
    stopped)
      supervisor_state=inactive
      graphical_state=inactive
      ;;
    failed)
      supervisor_state=failed
      graphical_state=error
      health=degraded
      reasons='["session-restart"]'
      last_error="{{\"code\":\"thin-client-exit\",\"message\":\"XAAC Thin Client ha finalitzat inesperadament\",\"occurred_at\":\"$now\",\"recoverable\":true}}"
      ;;
    degraded)
      supervisor_state=failed
      graphical_state=error
      health=unhealthy
      reasons='["restart-limit-exceeded"]'
      last_error="{{\"code\":\"session-degraded\",\"message\":\"El supervisor ha superat el límit de reinicis\",\"occurred_at\":\"$now\",\"recoverable\":false}}"
      ;;
    *) return 1 ;;
  esac
  umask 027
  tmp="$SHARED_STATE.tmp.$$"
  printf '{{"format":"xaac-state/v2","published_at":"%s","heartbeat_at":"%s","thin_client":{{"installed":true,"version":"%s"}},"supervisor":{{"state":"%s"}},"sessions":{{"graphical":{{"state":"%s"}},"rdp":{{"state":"unknown"}}}},"last_error":%s,"health":{{"status":"%s","reasons":%s}}}}\n' \
    "$now" "$now" "$version" "$supervisor_state" "$graphical_state" "$last_error" "$health" "$reasons" > "$tmp" || return 0
  chmod 0640 "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$SHARED_STATE" 2>/dev/null || rm -f "$tmp"
}}

prune_events() {{
  set -- "$EVENT_DIR"/*.json
  [ -e "$1" ] || return 0
  count=$#
  while [ "$count" -gt "$MAX_EVENTS" ]; do
    rm -f -- "$1" 2>/dev/null || true
    shift
    count=$((count - 1))
  done
}}

publish_event() {{
  event=$1; code=${{2:-0}}; attempts=${{3:-0}}; severity=${{4:-info}}
  [ -d "$EVENT_DIR" ] || return 0
  EVENT_SEQUENCE=$((EVENT_SEQUENCE + 1))
  now=$(iso_now)
  stamp=$(date -u '+%Y%m%dT%H%M%S')
  event_id="evt-$(date +%s)-$$-$EVENT_SEQUENCE"
  target="$EVENT_DIR/$stamp-$$-$EVENT_SEQUENCE.json"
  tmp="$target.tmp"
  umask 027
  printf '{{"format":"xaac-local-event/v1","event_id":"%s","source":"session-supervisor","event_type":"%s","timestamp":"%s","severity":"%s","data":{{"exit_code":%s,"restart_attempts":%s}}}}\n' \
    "$event_id" "$event" "$now" "$severity" "$code" "$attempts" > "$tmp" || return 0
  chmod 0640 "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$target" 2>/dev/null || rm -f "$tmp"
  prune_events
}}

heartbeat_loop() {{
  pid=$1; attempts=$2
  while kill -0 "$pid" 2>/dev/null; do
    sleep "$HEARTBEAT_SECONDS"
    kill -0 "$pid" 2>/dev/null || break
    write_shared_state running 0 "$attempts" || true
  done
}}

wait_for_graphics() {{
  if [ -n "${{WAYLAND_DISPLAY:-}}" ]; then
    socket="$RUNTIME_DIR/$WAYLAND_DISPLAY"
    waited=0
    while [ ! -S "$socket" ] && [ "$waited" -lt 30 ]; do
      sleep 1
      waited=$((waited + 1))
    done
    [ -S "$socket" ] || return 1
    return 0
  fi
  [ -n "${{DISPLAY:-}}" ]
}}

wait_for_startup_surface() {{
  pid=$1
  steps=$((STARTUP_READY_TIMEOUT * 10))
  waited=0
  while [ ! -f "$STARTUP_READY" ] && kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$steps" ]; do
    sleep 0.1
    waited=$((waited + 1))
  done
  [ -f "$STARTUP_READY" ]
}}

wait_for_interactive_surface() {{
  # Under Wayland, keep the busy overlay until either the VPN UI or the actual
  # Thin Client has a mapped toplevel. This makes the cursor reflect real work
  # instead of an arbitrary two-second delay.
  if [ -n "${{WAYLAND_DISPLAY:-}}" ] && command -v /usr/bin/wlrctl >/dev/null 2>&1; then
    steps=$((INTERACTIVE_TIMEOUT * 10))
    waited=0
    while [ "$waited" -lt "$steps" ]; do
      /usr/bin/wlrctl toplevel find "app_id:$THIN_CLIENT_APP_ID" >/dev/null 2>&1 && return 0
      /usr/bin/wlrctl toplevel find "app_id:$VPN_APP_ID" >/dev/null 2>&1 && return 0
      sleep 0.1
      waited=$((waited + 1))
    done
    return 1
  fi
  sleep "$STARTUP_MIN"
  return 0
}}

set_stable_background() {{
  if [ -n "${{WAYLAND_DISPLAY:-}}" ]; then
    if [ -r "$STABLE_BG_PID" ]; then
      stable_pid=$(cat "$STABLE_BG_PID" 2>/dev/null || true)
      if [ -n "$stable_pid" ] && kill -0 "$stable_pid" 2>/dev/null; then
        return 0
      fi
    fi
    "$BACKGROUND_COMMAND" -c "$STABLE_BACKGROUND" >/dev/null 2>&1 &
    stable_pid=$!
    printf '%s\\n' "$stable_pid" > "$STABLE_BG_PID"
    # The startup overlay is still covering the display while the neutral
    # background maps, so the handoff cannot expose the compositor canvas.
    sleep 0.1
    if [ -r "$HANDOFF_BG_PID" ]; then
      handoff_pid=$(cat "$HANDOFF_BG_PID" 2>/dev/null || true)
      [ -n "$handoff_pid" ] && kill "$handoff_pid" 2>/dev/null || true
      rm -f "$HANDOFF_BG_PID"
    fi
    return 0
  fi
  if [ -n "${{DISPLAY:-}}" ] && [ -x /usr/bin/xsetroot ]; then
    /usr/bin/xsetroot -solid "$STABLE_BACKGROUND" >/dev/null 2>&1 || true
  fi
}}

attempts=0
window_start=$(date +%s)
if ! wait_for_graphics; then
  write_status degraded 75 0
  write_shared_state degraded 75 0 || true
  publish_event session-degraded 75 0 error
  exec "$ERROR_SCREEN" 75 0 degraded 0
fi
while :; do
  started=$(date +%s)
  write_status starting 0 "$attempts"
  write_shared_state starting 0 "$attempts" || true
  publish_event session-starting 0 "$attempts" info
  rm -f "$STARTUP_READY"
  "$STARTUP_SCREEN" "$STARTUP_MIN" "$STARTUP_TIMEOUT" "$STARTUP_READY" &
  splash_pid=$!
  if ! wait_for_startup_surface "$splash_pid"; then
    publish_event visual-handoff-degraded 0 "$attempts" warning
  fi
  "$CLIENT" &
  client_pid=$!
  if ! wait_for_interactive_surface; then
    publish_event visual-interactive-timeout 0 "$attempts" warning
  fi
  set_stable_background
  kill "$splash_pid" 2>/dev/null || true
  wait "$splash_pid" 2>/dev/null || true
  rm -f "$STARTUP_READY"
  write_status running 0 "$attempts"
  write_shared_state running 0 "$attempts" || true
  publish_event session-running 0 "$attempts" info
  heartbeat_loop "$client_pid" "$attempts" &
  heartbeat_pid=$!
  wait "$client_pid"
  code=$?
  kill "$heartbeat_pid" 2>/dev/null || true
  wait "$heartbeat_pid" 2>/dev/null || true
  ended=$(date +%s)
  runtime=$((ended - started))
  case "$VOLUNTARY" in
    *" $code "*)
      write_status stopped "$code" "$attempts"
      write_shared_state stopped "$code" "$attempts" || true
      publish_event session-stopped "$code" "$attempts" info
      exit 0
      ;;
  esac
  [ "$runtime" -ge "$RESET_AFTER" ] && attempts=0 && window_start=$ended
  [ $((ended - window_start)) -gt "$WINDOW" ] && attempts=0 && window_start=$ended
  attempts=$((attempts + 1))
  write_status failed "$code" "$attempts"
  write_shared_state failed "$code" "$attempts" || true
  publish_event session-failed "$code" "$attempts" warning
  if [ "$attempts" -gt "$MAX_RESTARTS" ]; then
    write_status degraded "$code" "$attempts"
    write_shared_state degraded "$code" "$attempts" || true
    publish_event session-degraded "$code" "$attempts" error
    exec "$ERROR_SCREEN" "$code" "$attempts" degraded 0
  fi
  publish_event session-recovering "$code" "$attempts" info
  if ! "$ERROR_SCREEN" "$code" "$attempts" recovering "$BACKOFF"; then
    sleep "$BACKOFF"
  fi
  BACKOFF=$((BACKOFF * 2)); [ "$BACKOFF" -gt "$MAX_BACKOFF" ] && BACKOFF=$MAX_BACKOFF
done
'''
    startup_screen = r'''#!/usr/bin/python3.13
import os
import signal
import sys
from ctypes import CDLL, RTLD_GLOBAL
from pathlib import Path

_layer_library_loaded = False
if os.environ.get("WAYLAND_DISPLAY"):
    try:
        CDLL("libgtk4-layer-shell.so.0", mode=RTLD_GLOBAL)
        _layer_library_loaded = True
    except OSError:
        pass

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

LayerShell = None
if _layer_library_loaded:
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LayerShell
    except (ImportError, ValueError):
        LayerShell = None

minimum = max(1, int(sys.argv[1])) if len(sys.argv) > 1 else 2
timeout = max(minimum, int(sys.argv[2])) if len(sys.argv) > 2 else 20
ready_file = Path(sys.argv[3]) if len(sys.argv) > 3 else None
IMAGE = "/usr/share/plymouth/themes/xaac/XAAC_TC_OS.png"
BACKGROUND = "__HANDOFF_BACKGROUND__"


class StartupApp(Gtk.Application):
    def _mapped(self, *_args):
        if ready_file is not None:
            try:
                ready_file.write_text("mapped\n", encoding="utf-8")
            except OSError:
                pass

    def do_activate(self):
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("XAAC Thin Client")

        if LayerShell is not None and LayerShell.is_supported():
            LayerShell.init_for_window(window)
            LayerShell.set_namespace(window, "xaac-startup")
            LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
            for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
                LayerShell.set_anchor(window, edge, True)
        else:
            window.fullscreen()

        css = Gtk.CssProvider()
        css.load_from_data((
            "window { background: " + BACKGROUND + "; }"
        ).encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            window.get_display(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        picture = Gtk.Picture.new_for_filename(IMAGE)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_hexpand(True)
        picture.set_vexpand(True)

        window.set_child(picture)
        window.set_cursor_from_name("__BUSY_CURSOR__")
        window.connect("map", self._mapped)
        window.present()
        GLib.timeout_add_seconds(timeout, self.quit)


app = StartupApp(application_id="org.xaac.StartupScreen")
signal.signal(signal.SIGTERM, lambda *_: app.quit())
raise SystemExit(app.run(sys.argv[:1]))
'''
    startup_screen = (startup_screen
        .replace("__BUSY_CURSOR__", session_visual["busy_cursor_name"])
        .replace("__HANDOFF_BACKGROUND__", visual["background_color"])
    )
    error_screen = r'''#!/usr/bin/python3.13
import os
import signal
import sys
import time
from ctypes import CDLL, RTLD_GLOBAL

exit_code = int(sys.argv[1]) if len(sys.argv) > 1 else 1
attempts = int(sys.argv[2]) if len(sys.argv) > 2 else 0
mode = sys.argv[3] if len(sys.argv) > 3 else "degraded"
duration = max(0, int(sys.argv[4])) if len(sys.argv) > 4 else 0
if mode not in {"recovering", "degraded"}:
    mode = "degraded"

IMAGE = "__RECOVERY_IMAGE__"
BACKGROUND = "__RECOVERY_BACKGROUND__"
RECOVERY_TITLE = "__RECOVERY_TITLE__"
RECOVERY_MESSAGE = "__RECOVERY_MESSAGE__"
FAILURE_TITLE = "__FAILURE_TITLE__"
FAILURE_MESSAGE = "__FAILURE_MESSAGE__"
INCIDENT_PREFIX = "__INCIDENT_PREFIX__"
incident = f"SES-{exit_code:03d}-{attempts:02d}"


def console_fallback():
    # Keep tty1 XAAC-branded if the graphical stack itself is unavailable.
    try:
        with open("/dev/tty1", "w", encoding="utf-8", buffering=1) as tty:
            tty.write("\033[?25l\033[37;47m\033[2J\033[H\033[3J")
            tty.write("\n\nXAAC Thin Client\n\n")
            tty.write((RECOVERY_TITLE if mode == "recovering" else FAILURE_TITLE) + "\n")
            tty.write(f"{INCIDENT_PREFIX}: {incident}\n")
    except OSError:
        pass
    if duration > 0:
        time.sleep(duration)
        return 0
    while True:
        time.sleep(3600)


if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
    raise SystemExit(console_fallback())

_layer_library_loaded = False
if os.environ.get("WAYLAND_DISPLAY"):
    try:
        CDLL("libgtk4-layer-shell.so.0", mode=RTLD_GLOBAL)
        _layer_library_loaded = True
    except OSError:
        pass

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk
except (ImportError, ValueError):
    raise SystemExit(console_fallback())

LayerShell = None
if _layer_library_loaded:
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LayerShell
    except (ImportError, ValueError):
        LayerShell = None


class RecoveryApp(Gtk.Application):
    def do_activate(self):
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("XAAC Thin Client")
        window.set_cursor_from_name("__RECOVERY_BUSY_CURSOR__" if mode == "recovering" else "__NORMAL_CURSOR__")

        if LayerShell is not None and LayerShell.is_supported():
            LayerShell.init_for_window(window)
            LayerShell.set_namespace(window, "xaac-recovery")
            LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
            for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
                LayerShell.set_anchor(window, edge, True)
        else:
            window.fullscreen()

        css = Gtk.CssProvider()
        css.load_from_data((
            "window { background: " + BACKGROUND + "; color: #202124; font-family: Roboto, sans-serif; }"
            ".xaac-recovery-title { font-size: 30px; font-weight: 700; }"
            ".xaac-recovery-message { font-size: 17px; }"
            ".xaac-recovery-code { font-size: 14px; color: #5f6368; }"
        ).encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            window.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        layout.set_halign(Gtk.Align.CENTER)
        layout.set_valign(Gtk.Align.CENTER)
        layout.set_margin_start(48)
        layout.set_margin_end(48)

        picture = Gtk.Picture.new_for_filename(IMAGE)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_size_request(420, 180)

        title = Gtk.Label(label=RECOVERY_TITLE if mode == "recovering" else FAILURE_TITLE)
        title.add_css_class("xaac-recovery-title")
        title.set_justify(Gtk.Justification.CENTER)

        message = Gtk.Label(label=RECOVERY_MESSAGE if mode == "recovering" else FAILURE_MESSAGE)
        message.add_css_class("xaac-recovery-message")
        message.set_wrap(True)
        message.set_max_width_chars(60)
        message.set_justify(Gtk.Justification.CENTER)

        code = Gtk.Label(label=f"{INCIDENT_PREFIX}: {incident}")
        code.add_css_class("xaac-recovery-code")

        layout.append(picture)
        layout.append(title)
        layout.append(message)
        layout.append(code)
        window.set_child(layout)
        window.present()

        if duration > 0:
            GLib.timeout_add_seconds(duration, self._finish)

    def _finish(self):
        self.quit()
        return False


app = RecoveryApp(application_id="org.xaac.SessionRecovery")
signal.signal(signal.SIGTERM, lambda *_: app.quit())
raise SystemExit(app.run(sys.argv[:1]))
'''
    error_screen = (
        error_screen
        .replace("__RECOVERY_IMAGE__", recovery["background_image"])
        .replace("__RECOVERY_BACKGROUND__", recovery["background_color"])
        .replace("__RECOVERY_TITLE__", recovery["recovery_title"])
        .replace("__RECOVERY_MESSAGE__", recovery["recovery_message"])
        .replace("__FAILURE_TITLE__", recovery["failure_title"])
        .replace("__FAILURE_MESSAGE__", recovery["failure_message"])
        .replace("__INCIDENT_PREFIX__", recovery["incident_prefix"])
        .replace("__RECOVERY_BUSY_CURSOR__", session_visual["busy_cursor_name"])
        .replace("__NORMAL_CURSOR__", session_visual["normal_cursor_name"])
    )
    power_transition_screen = r'''#!/usr/bin/python3.13
import os
import signal
import sys
from ctypes import CDLL, RTLD_GLOBAL
from pathlib import Path

ACTION = sys.argv[1] if len(sys.argv) > 1 else "poweroff"
if ACTION not in {"poweroff", "reboot"}:
    raise SystemExit(64)
READY_FILE = Path(sys.argv[2]) if len(sys.argv) > 2 else None
IMAGE = "__POWER_IMAGE__"
BACKGROUND = "__POWER_BACKGROUND__"
POWEROFF_TITLE = "__POWEROFF_TITLE__"
POWEROFF_MESSAGE = "__POWEROFF_MESSAGE__"
REBOOT_TITLE = "__REBOOT_TITLE__"
REBOOT_MESSAGE = "__REBOOT_MESSAGE__"

_layer_library_loaded = False
if os.environ.get("WAYLAND_DISPLAY"):
    try:
        CDLL("libgtk4-layer-shell.so.0", mode=RTLD_GLOBAL)
        _layer_library_loaded = True
    except OSError:
        pass

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

LayerShell = None
if _layer_library_loaded:
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LayerShell
    except (ImportError, ValueError):
        LayerShell = None


class PowerTransitionApp(Gtk.Application):
    def _mapped(self, *_args):
        if READY_FILE is not None:
            try:
                READY_FILE.write_text("mapped\n", encoding="utf-8")
            except OSError:
                pass

    def do_activate(self):
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("XAAC Thin Client")
        window.set_cursor_from_name("__POWER_BUSY_CURSOR__")

        if LayerShell is not None and LayerShell.is_supported():
            LayerShell.init_for_window(window)
            LayerShell.set_namespace(window, "xaac-power-transition")
            LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
            for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
                LayerShell.set_anchor(window, edge, True)
        else:
            window.fullscreen()

        css = Gtk.CssProvider()
        css.load_from_data((
            "window { background: " + BACKGROUND + "; color: #202124; font-family: Roboto, sans-serif; }"
            ".xaac-power-title { font-size: 30px; font-weight: 700; }"
            ".xaac-power-message { font-size: 17px; }"
        ).encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            window.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        layout.set_halign(Gtk.Align.CENTER)
        layout.set_valign(Gtk.Align.CENTER)
        layout.set_margin_start(48)
        layout.set_margin_end(48)

        picture = Gtk.Picture.new_for_filename(IMAGE)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_size_request(420, 180)

        title_text = POWEROFF_TITLE if ACTION == "poweroff" else REBOOT_TITLE
        message_text = POWEROFF_MESSAGE if ACTION == "poweroff" else REBOOT_MESSAGE
        title = Gtk.Label(label=title_text)
        title.add_css_class("xaac-power-title")
        title.set_justify(Gtk.Justification.CENTER)
        message = Gtk.Label(label=message_text)
        message.add_css_class("xaac-power-message")
        message.set_wrap(True)
        message.set_max_width_chars(60)
        message.set_justify(Gtk.Justification.CENTER)
        spinner = Gtk.Spinner()
        spinner.start()

        layout.append(picture)
        layout.append(title)
        layout.append(message)
        layout.append(spinner)
        window.set_child(layout)
        window.connect("map", self._mapped)
        window.present()


app = PowerTransitionApp(application_id="org.xaac.PowerTransition")
signal.signal(signal.SIGTERM, lambda *_: app.quit())
signal.signal(signal.SIGINT, lambda *_: app.quit())
raise SystemExit(app.run(sys.argv[:1]))
'''
    power_transition_screen = (
        power_transition_screen
        .replace("__POWER_IMAGE__", power["background_image"])
        .replace("__POWER_BACKGROUND__", power["background_color"])
        .replace("__POWEROFF_TITLE__", power["poweroff_title"])
        .replace("__POWEROFF_MESSAGE__", power["poweroff_message"])
        .replace("__REBOOT_TITLE__", power["reboot_title"])
        .replace("__REBOOT_MESSAGE__", power["reboot_message"])
        .replace("__POWER_BUSY_CURSOR__", session_visual["busy_cursor_name"])
    )
    policy_payload = dict(cfg)
    policy_payload["visual_handoff"] = visual
    policy_payload["visual_session"] = session_visual
    policy_payload["visual_recovery"] = recovery
    policy_payload["visual_power"] = power
    policy = json.dumps(policy_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    autostart = f'''#!/bin/sh
# Managed by XAAC Thin Client OS — Block 8.5 — branded handoff, neutral stable session
runtime_dir=${{XDG_RUNTIME_DIR:-/run/user/$(id -u)}}
mkdir -p "$runtime_dir"
{visual["background_command"]} -i {visual["background_image"]} -m fit -c '{visual["background_color"]}' >/dev/null 2>&1 &
printf '%s\\n' "$!" > "$runtime_dir/xaac-handoff-background.pid"
{cfg["supervisor_command"]} &
'''
    planned = (
        (_safe_absolute(files["supervisor"], "supervisor"), supervisor, 0o755),
        (_safe_absolute(files["error_screen"], "error_screen"), error_screen, 0o755),
        (_safe_absolute(files["startup_screen"], "startup_screen"), startup_screen, 0o755),
        (_safe_absolute(files["power_transition_screen"], "power_transition_screen"), power_transition_screen, 0o755),
        (_safe_absolute(files["policy"], "policy"), policy, 0o644),
        (_safe_absolute(files["labwc_autostart"], "labwc_autostart"), autostart, 0o755),
    )
    packages = tuple(dict.fromkeys(profile["packages"]["required"]))
    return SessionSupervisorPlan(root, packages, planned)


class SessionSupervisorConfigurator:
    def execute(self, plan: SessionSupervisorPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for rel, content, mode in plan.files:
            target = plan.rootfs / str(rel).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise SessionSupervisorError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temp = target.with_name(target.name + ".tmp")
            temp.write_text(content, encoding="utf-8")
            temp.chmod(mode)
            temp.replace(target)
            written.append(target)
        return tuple(written)
