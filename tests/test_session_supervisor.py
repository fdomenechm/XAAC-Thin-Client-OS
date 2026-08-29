from pathlib import Path
import subprocess
import pytest

from xaac_thin_client_os.session_supervisor import (
    SessionSupervisorConfigurator, SessionSupervisorError,
    create_session_supervisor_plan, load_session_supervisor_profile,
)


def _script(tmp_path: Path, project_root: Path) -> str:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    return next(c for p, c, _ in plan.files if str(p).endswith("xaac-session-supervisor"))


def test_profile_has_bounded_restart_and_local_contract(project_root: Path) -> None:
    p = load_session_supervisor_profile(project_root / "config/session-supervisor.yaml")
    s = p["supervision"]
    assert s["max_restarts"] == 5
    assert s["initial_backoff_seconds"] < s["maximum_backoff_seconds"]
    assert s["shared_state_file"] == "/var/lib/xaac/thin-client/state/state.json"
    assert s["event_directory"] == "/run/xaac/thin-client/events"
    assert s["thin_client_package"] == "xaac-thinclient"
    assert s["state_heartbeat_seconds"] == 30


def test_plan_no_longer_depends_on_socat(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    assert {"python3.13", "python3-gi", "gir1.2-gtk-4.0"} <= set(plan.packages)
    assert "socat" not in plan.packages


def test_supervisor_restarts_with_backoff_and_limit(tmp_path: Path, project_root: Path) -> None:
    script = _script(tmp_path, project_root)
    assert 'attempts=$((attempts + 1))' in script
    assert 'BACKOFF=$((BACKOFF * 2))' in script
    assert 'if [ "$attempts" -gt "$MAX_RESTARTS" ]' in script


def test_supervisor_publishes_state_v2_and_bounded_events(tmp_path: Path, project_root: Path) -> None:
    script = _script(tmp_path, project_root)
    assert '"format":"xaac-state/v2"' in script
    assert '"supervisor":{"state":"%s"}' in script
    assert '"rdp":{"state":"unknown"}' in script
    assert '"format":"xaac-local-event/v1"' in script
    assert 'MAX_EVENTS=128' in script
    assert 'prune_events()' in script
    assert 'heartbeat_loop()' in script
    assert 'HEARTBEAT_SECONDS=30' in script


def test_supervisor_has_no_legacy_agent_socket(tmp_path: Path, project_root: Path) -> None:
    script = _script(tmp_path, project_root)
    assert "AGENT_SOCKET" not in script
    assert "socat" not in script
    assert "session-events.sock" not in script
    assert "agent.sock" not in script


def test_generated_supervisor_is_posix_shell_syntax(tmp_path: Path, project_root: Path) -> None:
    script = _script(tmp_path, project_root)
    path = tmp_path / "supervisor.sh"
    path.write_text(script)
    completed = subprocess.run(["/bin/sh", "-n", str(path)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_voluntary_exit_publishes_stopped_state(tmp_path: Path, project_root: Path) -> None:
    script = _script(tmp_path, project_root)
    assert 'write_status stopped' in script
    assert 'write_shared_state stopped' in script
    assert 'publish_event session-stopped' in script
    assert 'exit 0' in script


def test_error_screen_is_fullscreen_gtk4(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    script = next(c for p, c, _ in plan.files if str(p).endswith("xaac-session-error"))
    assert 'gi.require_version("Gtk", "4.0")' in script
    assert "window.fullscreen()" in script
    assert "mode segur" in script


def test_autostart_launches_supervisor(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    content, mode = next((c, m) for p, c, m in plan.files if str(p).endswith("labwc/autostart"))
    assert "/usr/local/libexec/xaac-session-supervisor &" in content
    assert mode == 0o755


def test_policy_is_json(tmp_path: Path, project_root: Path) -> None:
    import json
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    content = next(c for p, c, _ in plan.files if str(p).endswith("session-supervisor-policy.json"))
    policy = json.loads(content)
    assert policy["max_restarts"] == 5
    assert policy["shared_state_file"] == "/var/lib/xaac/thin-client/state/state.json"


def test_execute_is_idempotent(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    cfg = SessionSupervisorConfigurator()
    assert cfg.execute(plan, dry_run=True) == ()
    first = cfg.execute(plan)
    before = tuple((p.read_text(), p.stat().st_mode & 0o777) for p in first)
    second = cfg.execute(plan)
    assert tuple((p.read_text(), p.stat().st_mode & 0o777) for p in second) == before


def test_unsafe_rootfs_and_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    with pytest.raises(SessionSupervisorError, match="Rootfs insegur"):
        create_session_supervisor_plan(Path("/"), project_root / "config/session-supervisor.yaml")
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    target = plan.rootfs / "usr/local/libexec/xaac-session-supervisor"
    target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "other")
    with pytest.raises(SessionSupervisorError, match="enllaç simbòlic"):
        SessionSupervisorConfigurator().execute(plan)


@pytest.mark.parametrize("old,new", [
    ("user: xaac-kiosk", "user: root"),
    ("max_restarts: 5", "max_restarts: 50"),
    ("initial_backoff_seconds: 2", "initial_backoff_seconds: 60"),
    ("shared_state_file: /var/lib/xaac/thin-client/state/state.json", "shared_state_file: ../state.json"),
    ("event_directory: /run/xaac/thin-client/events", "event_directory: /tmp/events"),
    ("thin_client_package: xaac-thinclient", "thin_client_package: other"),
    ("    - gir1.2-gtk-4.0", "    - invalid-gtk"),
])
def test_invalid_profiles_rejected(tmp_path: Path, project_root: Path, old: str, new: str) -> None:
    content = (project_root / "config/session-supervisor.yaml").read_text().replace(old, new, 1)
    path = tmp_path / "profile.yaml"; path.write_text(content)
    with pytest.raises(SessionSupervisorError):
        load_session_supervisor_profile(path)


def test_supervisor_uses_numeric_xdg_runtime_and_waits_for_wayland(tmp_path: Path, project_root: Path) -> None:
    script = _script(tmp_path, project_root)
    assert 'RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}' in script
    assert 'STATUS="$RUNTIME_DIR/$STATUS_NAME"' in script
    assert '/run/user/xaac-kiosk/xaac-session-supervisor.json' not in script
    assert 'wait_for_graphics()' in script
    assert '[ -S "$socket" ]' in script



def test_session_entry_honours_dock_policy(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    files = {str(path): (content, mode) for path, content, mode in plan.files}
    script, mode = files["/usr/local/libexec/xaac-session-entry"]
    assert mode == 0o755
    assert "DOCK_CONFIG=/etc/xaac/xaac-thin-client-dock.ini" in script
    assert "disabled)" in script and 'exec "$LEGACY"' in script
    assert "optional|required)" in script and 'exec "$DOCK"' in script
    assert "exit 78" in script
    path = tmp_path / "session-entry.sh"
    path.write_text(script)
    completed = subprocess.run(["/bin/sh", "-n", str(path)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_supervisor_waits_for_dock_surface(tmp_path: Path, project_root: Path) -> None:
    script = _script(tmp_path, project_root)
    assert "DOCK_APP_ID=org.xaac.ThinClientDock" in script
    assert 'wlrctl toplevel find "app_id:$DOCK_APP_ID"' in script

def test_cli_exposes_supervisor_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["configure-session-supervisor", "--dry-run"])
    assert args.command == "configure-session-supervisor" and args.dry_run


def test_startup_screen_is_fullscreen_and_bounded(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    files = {str(p): c for p, c, _ in plan.files}
    splash = files["/usr/local/libexec/xaac-startup-screen"]
    supervisor = files["/usr/local/libexec/xaac-session-supervisor"]
    assert "window.fullscreen()" in splash
    assert 'LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)' in splash
    assert 'window.connect("map", self._mapped)' in splash
    assert 'IMAGE = "/usr/share/plymouth/themes/xaac/XAAC_TC_OS.png"' in splash
    assert "Gtk.Picture.new_for_filename(IMAGE)" in splash
    assert "Gtk.ContentFit.COVER" in splash
    assert "Gtk.Overlay()" in splash
    assert "Gtk.Spinner()" in splash
    assert 'spinner.set_margin_bottom(44)' in splash
    assert 'spinner.start()' in splash
    assert "BACKGROUND = \"#596166\"" in splash
    assert "window { background: " in splash
    assert '"$STARTUP_SCREEN" "$STARTUP_MIN" "$STARTUP_TIMEOUT" "$STARTUP_READY" &' in supervisor
    assert 'wait_for_startup_surface "$splash_pid"' in supervisor
    assert 'kill "$splash_pid"' in supervisor
    assert 'wait "$client_pid"' in supervisor
