from pathlib import Path


def test_zorin_theme_source_is_pinned_and_complete_installer_is_used(project_root: Path) -> None:
    source = (project_root / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "_install_zorin_icon_theme()" in source
    assert "zorin-icon-themes/archive/refs/tags/{version}.tar.gz" in source
    assert 'version = "3.3.1"' in source
    assert '("Zorin", "ZorinBlue-Light")' in source
    assert "/usr/share/icons/{theme_name}" in source
    assert "gtk-update-icon-cache" in source


def test_gtk_uses_zorin_blue_light(project_root: Path) -> None:
    source = (project_root / "src/xaac_thin_client_os/graphical_stack.py").read_text(encoding="utf-8")
    assert "gtk-icon-theme-name=ZorinBlue-Light" in source


def test_exact_zorin_gtk_theme_snapshot_is_bundled(project_root: Path) -> None:
    theme = project_root / "assets/zorin-theme/ZorinBlue-Light"
    assert (theme / "index.theme").is_file()
    assert (theme / "gtk-3.0/gtk.css").is_file()
    assert (theme / "gtk-4.0/gtk.css").is_file()
    source = (project_root / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "_install_zorin_gtk_theme()" in source
    assert 'assets/zorin-theme/ZorinBlue-Light' in source
    assert '/usr/share/themes/ZorinBlue-Light' in source


def test_gtk_theme_and_locked_client_decoration_are_selected(project_root: Path) -> None:
    graphical = (project_root / "src/xaac_thin_client_os/graphical_stack.py").read_text(encoding="utf-8")
    compositor = (project_root / "src/xaac_thin_client_os/compositor.py").read_text(encoding="utf-8")
    assert "gtk-theme-name=ZorinBlue-Light" in graphical
    assert "gtk-decoration-layout=:" in graphical
    assert "<decoration>client</decoration>" in compositor
    assert 'serverDecoration=\\\"no\\\"' in compositor
