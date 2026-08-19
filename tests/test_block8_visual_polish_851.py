from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace

from xaac_thin_client_os.compositor import create_compositor_plan
from xaac_thin_client_os.session_supervisor import create_session_supervisor_plan, load_session_supervisor_profile


def _supervisor_files(tmp_path: Path, project_root: Path) -> dict[str, str]:
    plan = create_session_supervisor_plan(
        tmp_path / "build/rootfs", project_root / "config/session-supervisor.yaml"
    )
    return {path.as_posix(): content for path, content, _ in plan.files}


def _installer_script(project_root: Path) -> str:
    source_path = project_root / "src/xaac_thin_client_os/production_builder.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    expression = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "_atomic_write" or len(node.args) < 2:
            continue
        target = ast.get_source_segment(source, node.args[0]) or ""
        if "xaac-installer-welcome" in target:
            expression = node.args[1]
            break
    assert expression is not None
    code = compile(ast.Expression(expression), str(source_path), "eval")
    fake_self = SimpleNamespace(settings=SimpleNamespace(locale="ca_ES.UTF-8"))
    return eval(code, {"self": fake_self, "installed_kernel_cmdline": "quiet splash"})


def test_phase851_installer_uses_utf8_console_and_visible_cursor(project_root: Path) -> None:
    script = _installer_script(project_root)
    assert "export LANG=C.UTF-8" in script
    assert "export LC_ALL=C.UTF-8" in script
    assert "install_locale=ca_ES.UTF-8" in script
    assert "install_locale=es_ES.UTF-8" in script
    assert "install_locale=en_US.UTF-8" in script
    assert "export LANG=$install_locale" in script
    assert "export LC_ALL=$install_locale" in script
    assert "setupcon --force" in script
    assert "printf '\\033[?25h'" in script
    assert "setterm --cursor on" in script
    # The whole installer avoids the typographic apostrophe that can render as a box on TTY.
    assert "’" not in script
    assert "ca:no_disk)" in script and "detectat cap disc" in script
    assert "ca:summary)" in script and "OPERACIÓ" in script


def test_phase851_generated_installer_keeps_posix_shell_syntax(tmp_path: Path, project_root: Path) -> None:
    path = tmp_path / "xaac-installer-welcome"
    path.write_text(_installer_script(project_root), encoding="utf-8")
    result = subprocess.run(["/bin/sh", "-n", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_phase851_console_font_is_unicode_oriented(project_root: Path) -> None:
    localization = (project_root / "config/localization.yaml").read_text(encoding="utf-8")
    assert "charmap: UTF-8" in localization
    assert "font: Uni2-Terminus16" in localization


def test_phase851_labwc_reuses_existing_output_mode(tmp_path: Path, project_root: Path) -> None:
    plan = create_compositor_plan(tmp_path / "rootfs", project_root / "config/compositor.yaml")
    files = {path.as_posix(): content for path, content, _ in plan.files}
    assert "<reuseOutputMode>yes</reuseOutputMode>" in files["/etc/xaac/labwc/rc.xml"]


def test_phase851_boot_handoff_prepares_tty_before_plymouth_quits(project_root: Path) -> None:
    source = (project_root / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "xaac-boot-handoff.service" in source
    assert "Before=plymouth-quit.service greetd.service" in source
    assert "ExecStart=/usr/local/libexec/xaac-prepare-kiosk-vt" in source
    assert "Wants=xaac-boot-handoff.service" in source
    assert '"systemctl", "enable", "xaac-boot-handoff.service"' in source


def test_phase851_busy_overlay_waits_for_real_interactive_toplevel(tmp_path: Path, project_root: Path) -> None:
    profile = load_session_supervisor_profile(project_root / "config/session-supervisor.yaml")
    visual = profile["visual_session"]
    assert visual["thin_client_app_id"] == "org.xaac.thinclient"
    assert visual["vpn_app_id"] == "es.canals.xaac.ThinClientVPN"
    assert visual["interactive_window_timeout_seconds"] == 20
    assert "wlrctl" in profile["packages"]["required"]

    supervisor = _supervisor_files(tmp_path, project_root)["/usr/local/libexec/xaac-session-supervisor"]
    assert '/usr/bin/wlrctl toplevel find "app_id:$THIN_CLIENT_APP_ID"' in supervisor
    assert '/usr/bin/wlrctl toplevel find "app_id:$VPN_APP_ID"' in supervisor
    start_client = supervisor.index('"$CLIENT" &')
    wait_window = supervisor.index("wait_for_interactive_surface", start_client)
    stable = supervisor.index("set_stable_background", wait_window)
    remove_overlay = supervisor.index('kill "$splash_pid"', stable)
    assert start_client < wait_window < stable < remove_overlay
