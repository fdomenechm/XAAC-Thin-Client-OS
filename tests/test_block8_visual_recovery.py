from pathlib import Path
import json
import subprocess

from xaac_thin_client_os.session_supervisor import (
    create_session_supervisor_plan,
    load_session_supervisor_profile,
)


def _files(tmp_path: Path, project_root: Path) -> dict[str, str]:
    plan = create_session_supervisor_plan(
        tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml"
    )
    return {path.as_posix(): content for path, content, _ in plan.files}


def test_phase83_profile_defines_branded_recovery_surface(project_root: Path) -> None:
    profile = load_session_supervisor_profile(project_root / "config/session-supervisor.yaml")
    recovery = profile["visual_recovery"]
    assert recovery["background_color"] == "#ffffff"
    assert recovery["background_image"] == "/usr/share/plymouth/themes/xaac/XAAC_TC_OS.png"
    assert recovery["use_layer_shell"] is True
    assert recovery["recovery_title"] == "Recuperant la sessió XAAC"
    assert "XAAC Thin Client" in recovery["failure_title"]
    assert recovery["incident_prefix"] == "Codi d'incidència"


def test_failed_client_is_hidden_behind_recovery_surface_during_backoff(
    tmp_path: Path, project_root: Path
) -> None:
    supervisor = _files(tmp_path, project_root)["/usr/local/libexec/xaac-session-supervisor"]
    failed = supervisor.index('publish_event session-failed "$code" "$attempts" warning')
    recovering = supervisor.index('publish_event session-recovering "$code" "$attempts" info', failed)
    overlay = supervisor.index(
        'if ! "$ERROR_SCREEN" "$code" "$attempts" recovering "$BACKOFF"; then', recovering
    )
    next_backoff = supervisor.index('BACKOFF=$((BACKOFF * 2))', overlay)
    assert failed < recovering < overlay < next_backoff
    assert 'sleep "$BACKOFF"' in supervisor[overlay:next_backoff]


def test_restart_limit_enters_stable_xaac_error_surface(
    tmp_path: Path, project_root: Path
) -> None:
    supervisor = _files(tmp_path, project_root)["/usr/local/libexec/xaac-session-supervisor"]
    limit = supervisor.index('if [ "$attempts" -gt "$MAX_RESTARTS" ]')
    degraded = supervisor.index('publish_event session-degraded "$code" "$attempts" error', limit)
    terminal = supervisor.index(
        'exec "$ERROR_SCREEN" "$code" "$attempts" degraded 0', degraded
    )
    assert limit < degraded < terminal


def test_graphical_error_surface_is_xaac_overlay_not_generic_dialog(
    tmp_path: Path, project_root: Path
) -> None:
    error = _files(tmp_path, project_root)["/usr/local/libexec/xaac-session-error"]
    assert 'LayerShell.set_namespace(window, "xaac-recovery")' in error
    assert 'LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)' in error
    assert 'Gtk.Picture.new_for_filename(IMAGE)' in error
    assert 'font-family: Roboto, sans-serif' in error
    assert 'incident = f"SES-{exit_code:03d}-{attempts:02d}"' in error
    assert "Gtk.MessageDialog" not in error
    assert "Gtk.AlertDialog" not in error
    assert "systemctl" not in error
    assert "factory-reset" not in error


def test_error_surface_has_console_fallback_without_debian_login(
    tmp_path: Path, project_root: Path
) -> None:
    error = _files(tmp_path, project_root)["/usr/local/libexec/xaac-session-error"]
    assert 'open("/dev/tty1", "w"' in error
    assert r'\033[?25l\033[37;47m\033[2J\033[H\033[3J' in error
    assert "XAAC Thin Client" in error
    assert 'not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY")' in error
    assert "/bin/login" not in error
    assert "agetty" not in error
    assert "traceback" not in error.lower()


def test_phase83_policy_serializes_visual_recovery(tmp_path: Path, project_root: Path) -> None:
    policy = _files(tmp_path, project_root)[
        "/etc/xaac/session/session-supervisor-policy.json"
    ]
    payload = json.loads(policy)
    assert payload["visual_recovery"]["use_layer_shell"] is True
    assert payload["visual_recovery"]["failure_title"] == "XAAC Thin Client no està disponible"


def test_generated_phase83_error_screen_has_valid_python_syntax(
    tmp_path: Path, project_root: Path
) -> None:
    error = _files(tmp_path, project_root)["/usr/local/libexec/xaac-session-error"]
    path = tmp_path / "xaac-session-error.py"
    path.write_text(error, encoding="utf-8")
    result = subprocess.run(
        ["python", "-m", "py_compile", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_generated_phase83_supervisor_remains_posix_shell(
    tmp_path: Path, project_root: Path
) -> None:
    supervisor = _files(tmp_path, project_root)["/usr/local/libexec/xaac-session-supervisor"]
    path = tmp_path / "xaac-session-supervisor.sh"
    path.write_text(supervisor, encoding="utf-8")
    result = subprocess.run(["/bin/sh", "-n", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
