from pathlib import Path
import pytest
from xaac_thin_client_os.graphical_stack import (
    GraphicalStackConfigurator, GraphicalStackError, GraphicalStackInventory,
    compare_graphical_stack, create_graphical_stack_plan, load_graphical_stack_profile,
)


def valid_inventory(**changes: object) -> GraphicalStackInventory:
    values = dict(session_type="wayland", display=None, wayland_display="wayland-0", gtk_major=4,
                  renderer="Mesa Intel HD Graphics", width=1920, height=1080,
                  keyboard_present=True, pointer_present=True)
    values.update(changes)
    return GraphicalStackInventory(**values)  # type: ignore[arg-type]


def test_profile_loads(project_root: Path) -> None:
    profile = load_graphical_stack_profile(project_root / "config/graphical-stack.yaml")
    assert profile["backend"]["primary"] == "wayland"
    assert profile["backend"]["fallback"] == "x11"

@pytest.mark.parametrize("content", ["[]\n", "schema_version: 2\n", "schema_version: 1\nprofile: x\n"])
def test_invalid_profile_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "stack.yaml"; path.write_text(content, encoding="utf-8")
    with pytest.raises(GraphicalStackError): load_graphical_stack_profile(path)

def test_wayland_stack_passes(project_root: Path) -> None:
    report = compare_graphical_stack(valid_inventory(), load_graphical_stack_profile(project_root / "config/graphical-stack.yaml"))
    assert report.compatible
    assert all(c.status == "pass" for c in report.checks)

def test_x11_fallback_passes(project_root: Path) -> None:
    report = compare_graphical_stack(valid_inventory(session_type="x11", display=":0", wayland_display=None), load_graphical_stack_profile(project_root / "config/graphical-stack.yaml"))
    assert report.compatible

@pytest.mark.parametrize("changes,failed", [
    ({"session_type": "tty"}, "backend"), ({"gtk_major": 3}, "gtk"), ({"renderer": None}, "renderer"),
    ({"width": 800}, "resolution"), ({"keyboard_present": False}, "keyboard"), ({"pointer_present": False}, "pointer"),
])
def test_runtime_failures_are_reported(project_root: Path, changes: dict[str, object], failed: str) -> None:
    report = compare_graphical_stack(valid_inventory(**changes), load_graphical_stack_profile(project_root / "config/graphical-stack.yaml"))
    assert not report.compatible
    assert next(c for c in report.checks if c.name == failed).status == "fail"

def test_plan_contains_minimal_packages_and_environment(tmp_path: Path, project_root: Path) -> None:
    plan = create_graphical_stack_plan(tmp_path / "build/rootfs", project_root / "config/graphical-stack.yaml")
    assert "libgtk-4-1" in plan.packages and "mesa-utils" in plan.packages
    assert "gnome-shell" in plan.forbidden_packages
    assert plan.files[0][0].as_posix() == "/etc/xaac/session/graphical-stack.env"

def test_execute_is_idempotent(tmp_path: Path, project_root: Path) -> None:
    plan = create_graphical_stack_plan(tmp_path / "build/rootfs", project_root / "config/graphical-stack.yaml")
    configurator = GraphicalStackConfigurator()
    assert configurator.execute(plan, dry_run=True) == ()
    first = configurator.execute(plan); before = first[0].read_text(encoding="utf-8")
    second = configurator.execute(plan); assert second[0].read_text(encoding="utf-8") == before

def test_unsafe_rootfs_and_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    with pytest.raises(GraphicalStackError, match="Rootfs insegur"):
        create_graphical_stack_plan(Path("/"), project_root / "config/graphical-stack.yaml")
    plan = create_graphical_stack_plan(tmp_path / "build/rootfs", project_root / "config/graphical-stack.yaml")
    target = plan.rootfs / "etc/xaac/session/graphical-stack.env"; target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "other")
    with pytest.raises(GraphicalStackError, match="enllaç simbòlic"):
        GraphicalStackConfigurator().execute(plan)

def test_cli_parser_exposes_graphical_stack() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["configure-graphical-stack", "--dry-run"])
    assert args.command == "configure-graphical-stack"
    assert args.dry_run is True

def test_roboto_is_default_font_family(project_root: Path) -> None:
    profile = load_graphical_stack_profile(project_root / "config/graphical-stack.yaml")
    assert profile["fonts"]["default_family"] == "Roboto"
    assert profile["fonts"]["sans_fallbacks"] == ["Noto Sans", "DejaVu Sans"]


def test_font_packages_are_included(tmp_path: Path, project_root: Path) -> None:
    plan = create_graphical_stack_plan(tmp_path / "build/rootfs", project_root / "config/graphical-stack.yaml")
    assert "fontconfig" in plan.packages
    assert "fonts-roboto" in plan.packages
    assert "fonts-noto-core" in plan.packages
    assert "fonts-dejavu-core" in plan.packages
    assert "adwaita-icon-theme" in plan.packages
    assert "adwaita-icon-theme-legacy" in plan.packages
    assert "hicolor-icon-theme" in plan.packages


def test_fontconfig_and_gtk4_files_are_planned(tmp_path: Path, project_root: Path) -> None:
    plan = create_graphical_stack_plan(tmp_path / "build/rootfs", project_root / "config/graphical-stack.yaml")
    files = {path.as_posix(): content for path, content, _ in plan.files}
    fontconfig = files["/etc/fonts/conf.d/60-xaac-default-fonts.conf"]
    assert "<family>Roboto</family>" in fontconfig
    assert fontconfig.index("<family>Roboto</family>") < fontconfig.index("<family>Noto Sans</family>")
    assert fontconfig.index("<family>Noto Sans</family>") < fontconfig.index("<family>DejaVu Sans</family>")
    expected_gtk = (
        "[Settings]\n"
        "gtk-font-name=Roboto 10\n"
        "gtk-theme-name=ZorinBlue-Light\n"
        "gtk-icon-theme-name=ZorinBlue-Light\n"
        "gtk-decoration-layout=:\n"
    )
    assert files["/etc/gtk-3.0/settings.ini"] == expected_gtk
    assert files["/etc/gtk-4.0/settings.ini"] == expected_gtk


def test_font_configuration_is_written_idempotently(tmp_path: Path, project_root: Path) -> None:
    plan = create_graphical_stack_plan(tmp_path / "build/rootfs", project_root / "config/graphical-stack.yaml")
    configurator = GraphicalStackConfigurator()
    first = configurator.execute(plan)
    assert len(first) == 4
    fontconfig = plan.rootfs / "etc/fonts/conf.d/60-xaac-default-fonts.conf"
    gtk3_settings = plan.rootfs / "etc/gtk-3.0/settings.ini"
    gtk_settings = plan.rootfs / "etc/gtk-4.0/settings.ini"
    before = (fontconfig.read_text(encoding="utf-8"), gtk3_settings.read_text(encoding="utf-8"), gtk_settings.read_text(encoding="utf-8"))
    configurator.execute(plan)
    after = (fontconfig.read_text(encoding="utf-8"), gtk3_settings.read_text(encoding="utf-8"), gtk_settings.read_text(encoding="utf-8"))
    assert after == before


@pytest.mark.parametrize(
    "replacement",
    [
        "default_family: Arial",
        "default_size: 0",
        "fontconfig_file: ../unsafe.conf",
    ],
)
def test_invalid_font_configuration_is_rejected(tmp_path: Path, project_root: Path, replacement: str) -> None:
    original = (project_root / "config/graphical-stack.yaml").read_text(encoding="utf-8")
    if replacement.startswith("default_family"):
        content = original.replace("default_family: Roboto", replacement)
    elif replacement.startswith("default_size"):
        content = original.replace("default_size: 10", replacement)
    else:
        content = original.replace("fontconfig_file: /etc/fonts/conf.d/60-xaac-default-fonts.conf", replacement)
    profile = tmp_path / "graphical-stack.yaml"
    profile.write_text(content, encoding="utf-8")
    with pytest.raises(GraphicalStackError):
        load_graphical_stack_profile(profile)
