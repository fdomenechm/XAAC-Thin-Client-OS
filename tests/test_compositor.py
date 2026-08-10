from pathlib import Path
import pytest
from xaac_thin_client_os.compositor import (
    CompositorConfigurator, CompositorError, CompositorInventory,
    compare_compositor, create_compositor_plan, load_compositor_profile,
)

def valid_inventory(**changes: object) -> CompositorInventory:
    values = dict(backend="wayland", process_running=True, output_count=2,
                  widths=(1920, 1280), heights=(1080, 1024), fullscreen=True,
                  decorations=False, panel_present=False, restart_count=0)
    values.update(changes)
    return CompositorInventory(**values)  # type: ignore[arg-type]

def test_profile_selects_labwc_and_openbox(project_root: Path) -> None:
    profile = load_compositor_profile(project_root / "config/compositor.yaml")
    assert profile["wayland"]["compositor"] == "labwc"
    assert profile["x11"]["window_manager"] == "openbox"

def test_wayland_and_x11_are_accepted(project_root: Path) -> None:
    profile = load_compositor_profile(project_root / "config/compositor.yaml")
    assert compare_compositor(valid_inventory(), profile).compatible
    assert compare_compositor(valid_inventory(backend="x11"), profile).compatible

def test_dual_monitor_is_validated(project_root: Path) -> None:
    report = compare_compositor(valid_inventory(), load_compositor_profile(project_root / "config/compositor.yaml"))
    assert next(c for c in report.checks if c.name == "outputs").status == "pass"
    assert next(c for c in report.checks if c.name == "resolution").status == "pass"

@pytest.mark.parametrize("changes,failed", [
    ({"process_running": False}, "process"),
    ({"output_count": 0, "widths": (), "heights": ()}, "outputs"),
    ({"widths": (800, 1280)}, "resolution"),
    ({"fullscreen": False}, "fullscreen"),
    ({"decorations": True}, "decorations"),
    ({"panel_present": True}, "panel"),
    ({"restart_count": 6}, "restart-limit"),
])
def test_runtime_failures(project_root: Path, changes: dict[str, object], failed: str) -> None:
    report = compare_compositor(valid_inventory(**changes), load_compositor_profile(project_root / "config/compositor.yaml"))
    assert not report.compatible
    assert next(c for c in report.checks if c.name == failed).status == "fail"

def test_plan_contains_minimal_packages_and_files(tmp_path: Path, project_root: Path) -> None:
    plan = create_compositor_plan(tmp_path / "build/rootfs", project_root / "config/compositor.yaml")
    assert {"labwc", "openbox", "xwayland", "wlr-randr"} <= set(plan.packages)
    assert {"waybar", "tint2", "rofi", "wofi"} <= set(plan.forbidden_packages)
    files = {p.as_posix(): content for p, content, _ in plan.files}
    assert "/etc/xaac/labwc/rc.xml" in files
    rc = files["/etc/xaac/labwc/rc.xml"]
    assert "<policy>center</policy>" in rc
    assert "<decoration>client</decoration>" in rc
    assert "<cornerRadius>12</cornerRadius>" in rc
    assert 'name="AutoPlace" policy="center"' in rc
    assert "ToggleFullscreen" not in rc
    assert "<keyboard />" in files["/etc/xaac/openbox/rc.xml"]

def test_execute_is_idempotent(tmp_path: Path, project_root: Path) -> None:
    plan = create_compositor_plan(tmp_path / "build/rootfs", project_root / "config/compositor.yaml")
    cfg = CompositorConfigurator()
    assert cfg.execute(plan, dry_run=True) == ()
    first = cfg.execute(plan)
    before = tuple(p.read_text(encoding="utf-8") for p in first)
    second = cfg.execute(plan)
    assert tuple(p.read_text(encoding="utf-8") for p in second) == before

def test_unsafe_rootfs_and_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    with pytest.raises(CompositorError, match="Rootfs insegur"):
        create_compositor_plan(Path("/"), project_root / "config/compositor.yaml")
    plan = create_compositor_plan(tmp_path / "build/rootfs", project_root / "config/compositor.yaml")
    target = plan.rootfs / "etc/xaac/labwc/rc.xml"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "other")
    with pytest.raises(CompositorError, match="enllaç simbòlic"):
        CompositorConfigurator().execute(plan)

@pytest.mark.parametrize("old,new", [
    ("compositor: labwc", "compositor: weston"),
    ("fullscreen: true", "fullscreen: false"),
    ("max_attempts: 5", "max_attempts: 0"),
    ("labwc_rc: /etc/xaac/labwc/rc.xml", "labwc_rc: ../unsafe.xml"),
])
def test_invalid_profiles_are_rejected(tmp_path: Path, project_root: Path, old: str, new: str) -> None:
    content = (project_root / "config/compositor.yaml").read_text(encoding="utf-8").replace(old, new)
    path = tmp_path / "compositor.yaml"; path.write_text(content, encoding="utf-8")
    with pytest.raises(CompositorError): load_compositor_profile(path)

def test_cli_exposes_compositor_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["configure-compositor", "--dry-run"])
    assert args.command == "configure-compositor" and args.dry_run
