from pathlib import Path
import subprocess
import sys

from xaac_thin_client_os.session_manager import create_session_manager_plan
from xaac_thin_client_os.session_supervisor import (
    create_session_supervisor_plan,
    load_session_supervisor_profile,
)


def _supervisor_files(tmp_path: Path, project_root: Path) -> dict[str, str]:
    plan = create_session_supervisor_plan(
        tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml"
    )
    return {path.as_posix(): content for path, content, _ in plan.files}


def test_visual_handoff_profile_is_xaac_branded(project_root: Path) -> None:
    profile = load_session_supervisor_profile(project_root / "config/session-supervisor.yaml")
    visual = profile["visual_handoff"]
    assert visual == {
        "background_color": "#596166",
        "background_image": "/usr/share/plymouth/themes/xaac/XAAC_TC_OS.png",
        "background_command": "/usr/bin/swaybg",
        "ready_timeout_seconds": 5,
        "use_layer_shell": True,
    }
    assert {"swaybg", "libgtk4-layer-shell0", "gir1.2-gtk4layershell-1.0"} <= set(
        profile["packages"]["required"]
    )


def test_wayland_handoff_maps_overlay_before_client(tmp_path: Path, project_root: Path) -> None:
    files = _supervisor_files(tmp_path, project_root)
    supervisor = files["/usr/local/libexec/xaac-session-supervisor"]
    startup = files["/usr/local/libexec/xaac-startup-screen"]

    start_screen = supervisor.index('"$STARTUP_SCREEN" "$STARTUP_MIN" "$STARTUP_TIMEOUT" "$STARTUP_READY" &')
    wait_surface = supervisor.index('wait_for_startup_surface "$splash_pid"', start_screen)
    start_client = supervisor.index('"$CLIENT" &', wait_surface)
    remove_overlay = supervisor.index('kill "$splash_pid"', start_client)
    assert start_screen < wait_surface < start_client < remove_overlay

    assert 'CDLL("libgtk4-layer-shell.so.0"' in startup
    assert 'LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)' in startup
    assert 'LayerShell.set_namespace(window, "xaac-startup")' in startup
    assert 'window.connect("map", self._mapped)' in startup
    assert 'ready_file.write_text("mapped\\n"' in startup


def test_labwc_background_precedes_supervisor(tmp_path: Path, project_root: Path) -> None:
    files = _supervisor_files(tmp_path, project_root)
    autostart = files["/etc/xaac/labwc/autostart"]
    background = "/usr/bin/swaybg -i /usr/share/plymouth/themes/xaac/XAAC_TC_OS.png -m fill -c '#596166'"
    assert background in autostart
    assert autostart.index("/usr/bin/swaybg") < autostart.index("/usr/local/libexec/xaac-session-supervisor")


def test_tty_and_x11_fallback_are_granite_not_generic_black(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_manager_plan(
        tmp_path / "build/rootfs", project_root / "config/session-manager.yaml"
    )
    files = {path.as_posix(): content for path, content, _ in plan.files}
    tty = files["/usr/local/libexec/xaac-prepare-kiosk-vt"]
    x11 = files["/usr/local/libexec/xaac-x11-session"]
    session = files["/usr/local/libexec/xaac-session"]
    assert "\\033[37;100m" in tty
    assert "\\033[?25l" in tty
    assert "/usr/local/libexec/xaac-prepare-kiosk-vt || true" in session
    assert "/usr/bin/xsetroot -solid '#596166'" in x11


def test_production_builder_installs_visual_handoff_dependencies(project_root: Path) -> None:
    source = (project_root / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    for package in ("swaybg", "libgtk4-layer-shell0", "gir1.2-gtk4layershell-1.0", "x11-xserver-utils"):
        assert f'"{package}"' in source
    assert "ExecStartPost=-/usr/bin/plymouth quit --retain-splash" in source
    assert "ExecStartPre=/usr/local/libexec/xaac-prepare-kiosk-vt" not in source


def test_generated_phase82_scripts_have_valid_syntax(tmp_path: Path, project_root: Path) -> None:
    supervisor_files = _supervisor_files(tmp_path, project_root)
    manager_plan = create_session_manager_plan(
        tmp_path / "manager/rootfs", project_root / "config/session-manager.yaml"
    )
    manager_files = {path.as_posix(): content for path, content, _ in manager_plan.files}

    shell_scripts = {
        "supervisor": supervisor_files["/usr/local/libexec/xaac-session-supervisor"],
        "autostart": supervisor_files["/etc/xaac/labwc/autostart"],
        "session": manager_files["/usr/local/libexec/xaac-session"],
        "x11": manager_files["/usr/local/libexec/xaac-x11-session"],
        "tty": manager_files["/usr/local/libexec/xaac-prepare-kiosk-vt"],
    }
    for name, content in shell_scripts.items():
        path = tmp_path / f"{name}.sh"
        path.write_text(content, encoding="utf-8")
        result = subprocess.run(["/bin/sh", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    startup = tmp_path / "startup.py"
    startup.write_text(supervisor_files["/usr/local/libexec/xaac-startup-screen"], encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "py_compile", str(startup)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
