from pathlib import Path
import pytest

from xaac_thin_client_os.session_supervisor import (
    SessionSupervisorConfigurator, SessionSupervisorError,
    create_session_supervisor_plan, load_session_supervisor_profile,
)


def test_profile_has_bounded_restart_policy(project_root: Path) -> None:
    p = load_session_supervisor_profile(project_root / "config/session-supervisor.yaml")
    s = p["supervision"]
    assert s["max_restarts"] == 5
    assert s["initial_backoff_seconds"] < s["maximum_backoff_seconds"]
    assert s["notify_agent"] is True


def test_plan_contains_supervisor_dependencies(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    assert {"python3.13", "python3-gi", "gir1.2-gtk-4.0", "socat"} <= set(plan.packages)


def test_supervisor_restarts_with_backoff_and_limit(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    files = {str(p): (c, m) for p, c, m in plan.files}
    script, mode = files["/usr/local/libexec/xaac-session-supervisor"]
    assert 'attempts=$((attempts + 1))' in script
    assert 'BACKOFF=$((BACKOFF * 2))' in script
    assert 'if [ "$attempts" -gt "$MAX_RESTARTS" ]' in script
    assert mode == 0o755


def test_voluntary_exit_stops_without_restart(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    script = next(c for p, c, _ in plan.files if str(p).endswith("xaac-session-supervisor"))
    assert 'write_status stopped' in script
    assert 'exit 0' in script


def test_error_screen_is_fullscreen_gtk4(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    script = next(c for p, c, _ in plan.files if str(p).endswith("xaac-session-error"))
    assert 'gi.require_version("Gtk", "4.0")' in script
    assert "window.fullscreen()" in script
    assert "mode segur" in script


def test_agent_notification_is_best_effort(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    script = next(c for p, c, _ in plan.files if str(p).endswith("xaac-session-supervisor"))
    assert '[ -S "$AGENT_SOCKET" ] || return 0' in script
    assert 'session-degraded' in script
    assert '|| true' in script


def test_autostart_launches_supervisor(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    content, mode = next((c, m) for p, c, m in plan.files if str(p).endswith("labwc/autostart"))
    assert "exec /usr/local/libexec/xaac-session-supervisor" in content
    assert "xaac-thin-client-launch" not in content
    assert mode == 0o755


def test_policy_is_json(tmp_path: Path, project_root: Path) -> None:
    import json
    plan = create_session_supervisor_plan(tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml")
    content = next(c for p, c, _ in plan.files if str(p).endswith("session-supervisor-policy.json"))
    assert json.loads(content)["max_restarts"] == 5


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
    ("notify_agent: true", "notify_agent: false"),
    ("max_restarts: 5", "max_restarts: 50"),
    ("initial_backoff_seconds: 2", "initial_backoff_seconds: 60"),
    ("agent_socket: /run/xaac-agent/session-events.sock", "agent_socket: ../socket"),
    ("    - gir1.2-gtk-4.0", "    - invalid-gtk"),
])
def test_invalid_profiles_rejected(tmp_path: Path, project_root: Path, old: str, new: str) -> None:
    content = (project_root / "config/session-supervisor.yaml").read_text().replace(old, new, 1)
    path = tmp_path / "profile.yaml"; path.write_text(content)
    with pytest.raises(SessionSupervisorError):
        load_session_supervisor_profile(path)


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
    assert "Iniciant l'aplicació" in splash
    assert "GLib.timeout_add_seconds(timeout, self.quit)" in splash
    assert '"$STARTUP_SCREEN" "$STARTUP_MIN" "$STARTUP_TIMEOUT" &' in supervisor
    assert 'kill "$splash_pid"' in supervisor
    assert 'wait "$client_pid"' in supervisor
