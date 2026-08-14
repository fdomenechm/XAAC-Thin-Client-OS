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
    for section in ("supervision", "packages", "files"):
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
    required = raw["packages"].get("required")
    if not isinstance(required, list) or not {"python3.13", "python3-gi", "gir1.2-gtk-4.0"} <= set(required):
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
    cfg, files = profile["supervision"], profile["files"]
    voluntary = " ".join(str(code) for code in cfg["voluntary_exit_codes"])
    status_name = PurePosixPath(str(cfg["status_file"])).name
    supervisor = f'''#!/bin/sh
set -u
CLIENT={cfg["client_command"]}
ERROR_SCREEN={cfg["error_screen_command"]}
STARTUP_SCREEN={cfg["startup_screen_command"]}
STARTUP_MIN={cfg["startup_screen_minimum_seconds"]}
STARTUP_TIMEOUT={cfg["startup_screen_timeout_seconds"]}
STATUS_NAME={status_name}
RUNTIME_DIR=${{XDG_RUNTIME_DIR:-/run/user/$(id -u)}}
STATUS="$RUNTIME_DIR/$STATUS_NAME"
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

attempts=0
window_start=$(date +%s)
if ! wait_for_graphics; then
  write_status degraded 75 0
  write_shared_state degraded 75 0 || true
  publish_event session-degraded 75 0 error
  exec "$ERROR_SCREEN" 75 0
fi
while :; do
  started=$(date +%s)
  write_status starting 0 "$attempts"
  write_shared_state starting 0 "$attempts" || true
  publish_event session-starting 0 "$attempts" info
  "$STARTUP_SCREEN" "$STARTUP_MIN" "$STARTUP_TIMEOUT" &
  splash_pid=$!
  "$CLIENT" &
  client_pid=$!
  sleep "$STARTUP_MIN"
  kill "$splash_pid" 2>/dev/null || true
  wait "$splash_pid" 2>/dev/null || true
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
    exec "$ERROR_SCREEN" "$code" "$attempts"
  fi
  sleep "$BACKOFF"
  BACKOFF=$((BACKOFF * 2)); [ "$BACKOFF" -gt "$MAX_BACKOFF" ] && BACKOFF=$MAX_BACKOFF
done
'''
    startup_screen = '''#!/usr/bin/python3.13
import gi
import signal
import sys

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

minimum = max(1, int(sys.argv[1])) if len(sys.argv) > 1 else 2
timeout = max(minimum, int(sys.argv[2])) if len(sys.argv) > 2 else 20
IMAGE = "/usr/share/plymouth/themes/xaac/XAAC_TC_OS.png"


class StartupApp(Gtk.Application):
    def do_activate(self):
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("XAAC Thin Client")
        window.fullscreen()

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            window {
                background: #ffffff;
            }
        """)
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
        window.present()
        GLib.timeout_add_seconds(timeout, self.quit)


app = StartupApp(application_id="org.xaac.StartupScreen")
signal.signal(signal.SIGTERM, lambda *_: app.quit())
raise SystemExit(app.run(sys.argv[:1]))
'''
    error_screen = '''#!/usr/bin/python3.13
import gi, sys
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

class ErrorApp(Gtk.Application):
    def do_activate(self):
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("XAAC Thin Client")
        window.fullscreen()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_halign(Gtk.Align.CENTER); box.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label="No s'ha pogut iniciar la sessió")
        title.add_css_class("title-1")
        detail = Gtk.Label(label="El sistema ha entrat en mode segur. Contacteu amb l'administrador.")
        detail.set_wrap(True); detail.set_justify(Gtk.Justification.CENTER)
        box.append(title); box.append(detail); window.set_child(box); window.present()

app = ErrorApp(application_id="org.xaac.SessionError")
raise SystemExit(app.run(sys.argv[:1]))
'''
    policy = json.dumps(cfg, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    autostart = f'''#!/bin/sh
# Managed by XAAC Thin Client OS — Block 7.3 — local Agent integration
{cfg["supervisor_command"]} &
'''
    planned = (
        (_safe_absolute(files["supervisor"], "supervisor"), supervisor, 0o755),
        (_safe_absolute(files["error_screen"], "error_screen"), error_screen, 0o755),
        (_safe_absolute(files["startup_screen"], "startup_screen"), startup_screen, 0o755),
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
