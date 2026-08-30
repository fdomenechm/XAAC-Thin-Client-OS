from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import sys

from xaac_thin_client_os.production_builder import ProductionIsoBuilder
from xaac_thin_client_os.session_supervisor import (
    create_session_supervisor_plan,
    load_session_supervisor_profile,
)


def _session_files(tmp_path: Path, project_root: Path) -> dict[str, str]:
    plan = create_session_supervisor_plan(
        tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml"
    )
    return {path.as_posix(): content for path, content, _ in plan.files}


def _power_runtime(tmp_path: Path) -> dict[str, str]:
    rootfs = tmp_path / "rootfs"
    config = rootfs / "etc/xaac-remote/config.ini"
    config.parent.mkdir(parents=True)
    config.write_text("[application]\nmode = development\n", encoding="utf-8")
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = SimpleNamespace(rootfs=rootfs)
    builder._configure_xaac_thinclient_production_runtime()
    paths = (
        "/usr/local/libexec/xaac/start-power-transition",
        "/usr/local/libexec/xaac/stop-power-transition",
        "/usr/local/sbin/xaac-kiosk-poweroff",
        "/usr/local/sbin/xaac-kiosk-reboot",
    )
    return {path: (rootfs / path.lstrip("/")).read_text(encoding="utf-8") for path in paths}



def test_production_runtime_enforces_freerdp_fullscreen(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    config = rootfs / "etc/xaac-remote/config.ini"
    config.parent.mkdir(parents=True)
    config.write_text(
        "[application]\nmode = development\n\n"
        "[rdp]\nfullscreen = false\ndynamic_resolution = false\n",
        encoding="utf-8",
    )
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = SimpleNamespace(rootfs=rootfs)
    builder._configure_xaac_thinclient_production_runtime()
    effective = config.read_text(encoding="utf-8")
    assert "mode = production" in effective
    assert "fullscreen = true" in effective
    assert "dynamic_resolution = false" in effective


def test_phase84_profile_defines_poweroff_and_reboot_surface(project_root: Path) -> None:
    profile = load_session_supervisor_profile(project_root / "config/session-supervisor.yaml")
    power = profile["visual_power"]
    assert power["background_color"] == "#ffffff"
    assert power["background_image"] == "/usr/share/plymouth/themes/xaac/XAAC_TC_OS.png"
    assert power["use_layer_shell"] is True
    assert power["ready_timeout_seconds"] == 2
    assert power["poweroff_title"] == "Apagant el terminal XAAC"
    assert power["reboot_title"] == "Reiniciant el terminal XAAC"


def test_phase84_power_surface_is_fullscreen_xaac_overlay(
    tmp_path: Path, project_root: Path
) -> None:
    screen = _session_files(tmp_path, project_root)["/usr/local/libexec/xaac-power-transition"]
    assert 'ACTION not in {"poweroff", "reboot"}' in screen
    assert 'LayerShell.set_namespace(window, "xaac-power-transition")' in screen
    assert 'LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)' in screen
    assert 'Gtk.Picture.new_for_filename(IMAGE)' in screen
    assert 'font-family: Roboto, sans-serif' in screen
    assert 'Gtk.Spinner()' in screen
    assert 'window.connect("map", self._mapped)' in screen
    assert 'READY_FILE.write_text("mapped\\n"' in screen
    assert "systemctl" not in screen
    assert "Debian" not in screen


def test_phase84_policy_serializes_visual_power(tmp_path: Path, project_root: Path) -> None:
    policy = _session_files(tmp_path, project_root)[
        "/etc/xaac/session/session-supervisor-policy.json"
    ]
    payload = json.loads(policy)
    assert payload["visual_power"]["poweroff_title"] == "Apagant el terminal XAAC"
    assert payload["visual_power"]["reboot_title"] == "Reiniciant el terminal XAAC"


def test_phase84_power_surface_has_valid_python_syntax(
    tmp_path: Path, project_root: Path
) -> None:
    screen = _session_files(tmp_path, project_root)["/usr/local/libexec/xaac-power-transition"]
    path = tmp_path / "xaac-power-transition.py"
    path.write_text(screen, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_phase84_root_launcher_discovers_kiosk_display_and_waits_only_bounded_time(
    tmp_path: Path,
) -> None:
    runtime = _power_runtime(tmp_path)
    launcher = runtime["/usr/local/libexec/xaac/start-power-transition"]
    assert 'runtime_dir=/run/user/$kiosk_uid' in launcher
    assert 'for socket in "$runtime_dir"/wayland-*' in launcher
    assert 'GDK_BACKEND=$backend' in launcher
    assert '/usr/sbin/runuser -u "$kiosk_user"' in launcher
    assert '"$screen" "$action" "$ready_file"' in launcher
    assert '[ "$steps" -lt 20 ]' in launcher
    assert "sleep 0.1" in launcher
    assert r"\033[?25l\033[37;100m\033[2J\033[H\033[3J" in launcher


def test_phase84_power_helpers_cover_screen_before_systemctl_and_cleanup_on_failure(
    tmp_path: Path,
) -> None:
    runtime = _power_runtime(tmp_path)
    for action in ("poweroff", "reboot"):
        helper = runtime[f"/usr/local/sbin/xaac-kiosk-{action}"]
        transition = f"/usr/local/libexec/xaac/start-power-transition {action} || true"
        systemctl = f"/usr/bin/systemctl {action}"
        assert transition in helper
        assert systemctl in helper
        assert helper.index(transition) < helper.index(systemctl)
        assert "/usr/local/libexec/xaac/stop-power-transition" in helper
        assert 'exit "$rc"' in helper


def test_phase84_generated_root_helpers_are_posix_shell(tmp_path: Path) -> None:
    runtime = _power_runtime(tmp_path)
    for index, content in enumerate(runtime.values()):
        path = tmp_path / f"power-helper-{index}.sh"
        path.write_text(content, encoding="utf-8")
        result = subprocess.run(["/bin/sh", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_phase84_shutdown_console_cleanup_hides_cursor_and_uses_neutral_canvas() -> None:
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "xaac-clear-console-before-shutdown.service" in source
    assert r"\033[?25l\033[37;100m\033[2J\033[H\033[3J" in source
    assert "Before=plymouth-poweroff.service plymouth-reboot.service plymouth-halt.service" in source
