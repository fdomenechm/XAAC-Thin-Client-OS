from pathlib import Path


def test_zorin_icon_subset_is_vendored(project_root: Path) -> None:
    theme = project_root / "assets/zorin-icons/ZorinBlue-Light"
    assert (theme / "index.theme").is_file()
    assert (theme / "scalable/devices/computer-symbolic.svg").is_file()
    assert (theme / "scalable/devices/network-server-symbolic.svg").is_file()
    assert (theme / "scalable/status/network-wired-symbolic.svg").is_file()
    assert (theme / "scalable/apps/utilities-system-monitor-symbolic.svg").is_file()
    assert (project_root / "assets/zorin-icons/LICENSE").is_file()


def test_production_builder_installs_visual_baseline(project_root: Path) -> None:
    source = (project_root / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "_install_zorin_icon_subset()" in source
    assert "create_graphical_stack_plan" in source
    assert "/usr/share/icons/ZorinBlue-Light" in source
