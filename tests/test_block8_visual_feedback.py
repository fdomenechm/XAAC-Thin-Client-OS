from pathlib import Path
import json
import subprocess

from xaac_thin_client_os.session_manager import create_session_manager_plan
from xaac_thin_client_os.session_supervisor import (
    create_session_supervisor_plan,
    load_session_supervisor_profile,
)


def _files(tmp_path: Path, project_root: Path) -> dict[str, str]:
    plan = create_session_supervisor_plan(
        tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml"
    )
    return {path.as_posix(): content for path, content, _ in plan.files}


def test_phase85_profile_separates_handoff_from_stable_session(project_root: Path) -> None:
    profile = load_session_supervisor_profile(project_root / "config/session-supervisor.yaml")
    assert profile["visual_handoff"]["background_color"] == "#383e42"
    assert profile["visual_handoff"]["background_image"].endswith("XAAC_TC_OS.png")
    stable = profile["visual_session"]
    assert stable["stable_background_color"] == "#383e42"
    assert stable["stable_background_color"] not in {"#000000", "#ffffff"}
    assert stable["busy_cursor_name"] == "wait"
    assert stable["normal_cursor_name"] == "default"
    assert stable["cursor_theme"] == "Adwaita"
    assert stable["cursor_size"] == 24


def test_phase85_wayland_background_switch_happens_behind_startup_overlay(
    tmp_path: Path, project_root: Path
) -> None:
    files = _files(tmp_path, project_root)
    supervisor = files["/usr/local/libexec/xaac-session-supervisor"]
    autostart = files["/etc/xaac/labwc/autostart"]
    assert "xaac-handoff-background.pid" in autostart
    assert "-i /usr/share/plymouth/themes/xaac/XAAC_TC_OS.png" in autostart
    assert 'STABLE_BACKGROUND=#383e42' in supervisor
    assert '"$BACKGROUND_COMMAND" -c "$STABLE_BACKGROUND"' in supervisor
    assert 'kill "$handoff_pid"' in supervisor
    start_client = supervisor.index('"$CLIENT" &')
    stable = supervisor.index("set_stable_background", start_client)
    remove_overlay = supervisor.index('kill "$splash_pid"', stable)
    assert start_client < stable < remove_overlay


def test_phase85_x11_stable_background_is_neutral(tmp_path: Path, project_root: Path) -> None:
    supervisor = _files(tmp_path, project_root)["/usr/local/libexec/xaac-session-supervisor"]
    assert '/usr/bin/xsetroot -solid "$STABLE_BACKGROUND"' in supervisor


def test_phase85_busy_cursor_is_used_only_for_busy_transition_surfaces(
    tmp_path: Path, project_root: Path
) -> None:
    files = _files(tmp_path, project_root)
    startup = files["/usr/local/libexec/xaac-startup-screen"]
    recovery = files["/usr/local/libexec/xaac-session-error"]
    power = files["/usr/local/libexec/xaac-power-transition"]
    assert 'window.set_cursor_from_name("wait")' in startup
    assert 'window.set_cursor_from_name("wait" if mode == "recovering" else "default")' in recovery
    assert 'window.set_cursor_from_name("wait")' in power


def test_phase85_session_exports_consistent_cursor_theme(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_manager_plan(
        tmp_path / "manager/rootfs", project_root / "config/session-manager.yaml"
    )
    files = {path.as_posix(): content for path, content, _ in plan.files}
    launcher = files["/usr/local/libexec/xaac-session"]
    environment = files["/etc/xaac/session/session-manager.env"]
    for content in (launcher, environment):
        assert "XCURSOR_THEME=Adwaita" in content
        assert "XCURSOR_SIZE=24" in content


def test_phase85_policy_serializes_visual_feedback(tmp_path: Path, project_root: Path) -> None:
    policy = _files(tmp_path, project_root)["/etc/xaac/session/session-supervisor-policy.json"]
    payload = json.loads(policy)
    assert payload["visual_session"]["stable_background_color"] == "#383e42"
    assert payload["visual_session"]["busy_cursor_name"] == "wait"


def test_phase85_generated_scripts_keep_valid_syntax(tmp_path: Path, project_root: Path) -> None:
    files = _files(tmp_path, project_root)
    for key in ("/usr/local/libexec/xaac-session-supervisor", "/etc/xaac/labwc/autostart"):
        path = tmp_path / (Path(key).name + ".sh")
        path.write_text(files[key], encoding="utf-8")
        result = subprocess.run(["/bin/sh", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    for key in (
        "/usr/local/libexec/xaac-startup-screen",
        "/usr/local/libexec/xaac-session-error",
        "/usr/local/libexec/xaac-power-transition",
    ):
        path = tmp_path / (Path(key).name + ".py")
        path.write_text(files[key], encoding="utf-8")
        result = subprocess.run(["python", "-m", "py_compile", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
