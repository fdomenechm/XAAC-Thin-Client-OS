from pathlib import Path

from xaac_thin_client_os.session_manager import create_session_manager_plan
from xaac_thin_client_os.session_supervisor import create_session_supervisor_plan


def _supervisor_files(tmp_path: Path, project_root: Path) -> dict[str, str]:
    plan = create_session_supervisor_plan(
        tmp_path / "rootfs", project_root / "config/session-supervisor.yaml"
    )
    return {path.as_posix(): content for path, content, _ in plan.files}


def test_phase87_startup_surface_covers_every_aspect_ratio_and_animates(
    tmp_path: Path, project_root: Path
) -> None:
    startup = _supervisor_files(tmp_path, project_root)["/usr/local/libexec/xaac-startup-screen"]
    assert "Gtk.ContentFit.COVER" in startup
    assert "Gtk.ContentFit.CONTAIN" not in startup
    assert "Gtk.Overlay()" in startup
    assert "Gtk.Spinner()" in startup
    assert 'spinner.start()' in startup
    assert 'window.set_cursor_from_name("wait")' in startup


def test_phase87_wayland_handoff_uses_fill_and_granite_canvas(
    tmp_path: Path, project_root: Path
) -> None:
    files = _supervisor_files(tmp_path, project_root)
    autostart = files["/etc/xaac/labwc/autostart"]
    supervisor = files["/usr/local/libexec/xaac-session-supervisor"]
    assert "-m fill" in autostart
    assert "-m fit" not in autostart
    assert "-c '#596166'" in autostart
    assert "STABLE_BACKGROUND=#596166" in supervisor


def test_phase87_wayland_path_does_not_erase_retained_plymouth_before_labwc(
    tmp_path: Path, project_root: Path
) -> None:
    plan = create_session_manager_plan(
        tmp_path / "manager/rootfs", project_root / "config/session-manager.yaml"
    )
    files = {path.as_posix(): content for path, content, _ in plan.files}
    launcher = files["/usr/local/libexec/xaac-session"]
    wayland = launcher.index("exec /usr/bin/labwc")
    prepare = launcher.index("/usr/local/libexec/xaac-prepare-kiosk-vt || true")
    assert wayland < prepare
    assert "/usr/bin/xsetroot -solid '#596166'" in files["/usr/local/libexec/xaac-x11-session"]


def test_phase87_boot_builder_retains_plymouth_and_forces_early_i915(project_root: Path) -> None:
    source = (project_root / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "plymouth quit --retain-splash" in source
    assert 'self._inside("/etc/initramfs-tools/modules")' in source
    assert '"i915\\n"' in source
    assert "xaac-intel-graphics.conf" in source
    assert "grep -Eq '/i915\\\\.ko" in source
    assert "ExecStartPre=/usr/local/libexec/xaac-prepare-kiosk-vt" not in source


def test_phase87_plymouth_cover_scaling_and_activity_indicator_are_built_in(project_root: Path) -> None:
    source = (project_root / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert 'if (scale_y > scale_x)' in source
    assert 'if (scale_y < scale_x)' not in source
    for index in range(3):
        asset = project_root / f"assets/branding/XAAC_loading_{index}.png"
        assert asset.is_file()
        assert asset.stat().st_size > 100
        assert f'XAAC_loading_{index}.png' in source
    assert "Plymouth.SetRefreshFunction(refresh_callback)" in source
    assert "Plymouth.SetRefreshRate(20)" in source
