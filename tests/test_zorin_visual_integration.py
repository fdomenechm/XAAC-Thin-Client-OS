from pathlib import Path


def test_zorin_theme_source_is_pinned_and_complete_installer_is_used(project_root: Path) -> None:
    source = (project_root / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "_install_zorin_icon_theme()" in source
    assert "zorin-icon-themes/archive/refs/tags/{version}.tar.gz" in source
    assert 'version = "4.0.8"' in source
    assert '("Zorin", "ZorinBlue-Light")' in source
    assert "/usr/share/icons/{theme_name}" in source
    assert "gtk-update-icon-cache" in source


def test_gtk_uses_zorin_blue_light(project_root: Path) -> None:
    source = (project_root / "src/xaac_thin_client_os/graphical_stack.py").read_text(encoding="utf-8")
    assert "gtk-icon-theme-name=ZorinBlue-Light" in source
