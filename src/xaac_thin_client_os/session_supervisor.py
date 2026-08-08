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
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise SessionSupervisorError("Perfil de supervisió invàlid o esquema no suportat")
    for section in ("supervision", "packages", "files"):
        if not isinstance(raw.get(section), dict):
            raise SessionSupervisorError(f"Secció obligatòria absent: {section}")
    cfg = raw["supervision"]
    if cfg.get("user") != "xaac-kiosk" or cfg.get("notify_agent") is not True:
        raise SessionSupervisorError("La supervisió ha d'usar xaac-kiosk i notificar l'Agent")
    for key in ("client_command", "supervisor_command", "error_screen_command", "startup_screen_command", "status_file", "agent_socket"):
        _safe_absolute(cfg.get(key), key)
    for key in ("max_restarts", "restart_window_seconds", "initial_backoff_seconds", "maximum_backoff_seconds", "reset_after_seconds", "startup_screen_minimum_seconds", "startup_screen_timeout_seconds"):
        if not isinstance(cfg.get(key), int) or cfg[key] <= 0:
            raise SessionSupervisorError(f"Valor de supervisió invàlid: {key}")
    if cfg["initial_backoff_seconds"] > cfg["maximum_backoff_seconds"] or cfg["max_restarts"] > 20:
        raise SessionSupervisorError("Política de reinici insegura")
    if cfg["startup_screen_minimum_seconds"] > cfg["startup_screen_timeout_seconds"]:
        raise SessionSupervisorError("Temporització de pantalla d'espera invàlida")
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
AGENT_SOCKET={cfg["agent_socket"]}
MAX_RESTARTS={cfg["max_restarts"]}
WINDOW={cfg["restart_window_seconds"]}
BACKOFF={cfg["initial_backoff_seconds"]}
MAX_BACKOFF={cfg["maximum_backoff_seconds"]}
RESET_AFTER={cfg["reset_after_seconds"]}
VOLUNTARY=" {voluntary} "

write_status() {{
  state=$1; code=${{2:-0}}; attempts=${{3:-0}}
  umask 077
  mkdir -p "$(dirname "$STATUS")"
  printf '{{"state":"%s","exit_code":%s,"restart_attempts":%s,"timestamp":%s}}\n' "$state" "$code" "$attempts" "$(date +%s)" > "$STATUS.tmp"
  mv "$STATUS.tmp" "$STATUS"
}}
notify_agent() {{
  event=$1; code=${{2:-0}}
  [ -S "$AGENT_SOCKET" ] || return 0
  printf '{{"event":"%s","exit_code":%s,"component":"xaac-thin-client"}}\n' "$event" "$code" | /usr/bin/socat - "UNIX-CONNECT:$AGENT_SOCKET" >/dev/null 2>&1 || true
}}

wait_for_graphics() {{
  # labwc exports WAYLAND_DISPLAY to autostart children, but the socket can
  # appear a fraction later.  Wait for the real socket instead of racing it.
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
  notify_agent session-degraded 75
  exec "$ERROR_SCREEN" 75 0
fi
while :; do
  started=$(date +%s)
  write_status starting 0 "$attempts"
  "$STARTUP_SCREEN" "$STARTUP_MIN" "$STARTUP_TIMEOUT" &
  splash_pid=$!
  "$CLIENT" &
  client_pid=$!
  sleep "$STARTUP_MIN"
  kill "$splash_pid" 2>/dev/null || true
  wait "$splash_pid" 2>/dev/null || true
  write_status running 0 "$attempts"
  wait "$client_pid"
  code=$?
  ended=$(date +%s)
  runtime=$((ended - started))
  case "$VOLUNTARY" in *" $code "*) write_status stopped "$code" "$attempts"; notify_agent session-stopped "$code"; exit 0;; esac
  [ "$runtime" -ge "$RESET_AFTER" ] && attempts=0 && window_start=$ended
  [ $((ended - window_start)) -gt "$WINDOW" ] && attempts=0 && window_start=$ended
  attempts=$((attempts + 1))
  write_status failed "$code" "$attempts"
  notify_agent session-failed "$code"
  if [ "$attempts" -gt "$MAX_RESTARTS" ]; then
    write_status degraded "$code" "$attempts"
    notify_agent session-degraded "$code"
    exec "$ERROR_SCREEN" "$code" "$attempts"
  fi
  sleep "$BACKOFF"
  BACKOFF=$((BACKOFF * 2)); [ "$BACKOFF" -gt "$MAX_BACKOFF" ] && BACKOFF=$MAX_BACKOFF
done
'''
    startup_screen = '''#!/usr/bin/python3.13
import gi, signal, sys
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

minimum = max(1, int(sys.argv[1])) if len(sys.argv) > 1 else 2
timeout = max(minimum, int(sys.argv[2])) if len(sys.argv) > 2 else 20

class StartupApp(Gtk.Application):
    def do_activate(self):
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("XAAC Thin Client")
        window.fullscreen()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_halign(Gtk.Align.CENTER); box.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label="XAAC Thin Client")
        title.add_css_class("title-1")
        message = Gtk.Label(label="Iniciant l'aplicació…")
        spinner = Gtk.Spinner(); spinner.start()
        box.append(title); box.append(spinner); box.append(message)
        window.set_child(box); window.present()
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
# Managed by XAAC Thin Client OS — Block 5 — definitive integration
{cfg["supervisor_command"]} &
'''
    planned = (
        (_safe_absolute(files["supervisor"], "supervisor"), supervisor, 0o755),
        (_safe_absolute(files["error_screen"], "error_screen"), error_screen, 0o755),
        (_safe_absolute(files["startup_screen"], "startup_screen"), startup_screen, 0o755),
        (_safe_absolute(files["policy"], "policy"), policy, 0o644),
        (_safe_absolute(files["labwc_autostart"], "labwc_autostart"), autostart, 0o755),
    )
    packages = tuple(dict.fromkeys([*profile["packages"]["required"], "socat"]))
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
