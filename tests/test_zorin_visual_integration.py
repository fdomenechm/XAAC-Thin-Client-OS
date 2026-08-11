from pathlib import Path


def test_production_builder_installs_vendored_zorin_icon_snapshot():
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert 'source_root = self.paths.project_root / "assets/zorin-icons"' in source
    assert '("Zorin", "ZorinBlue-Light")' in source
    assert 'shutil.copytree(source, destination, symlinks=True)' in source
    assert 'urlretrieve' not in source[source.index("def _install_zorin_icon_theme"):source.index("def _install_zorin_gtk_theme")]


def test_vendored_zorin_icon_snapshot_is_complete():
    root = Path("assets/zorin-icons")
    zorin = root / "Zorin"
    blue = root / "ZorinBlue-Light"
    assert (zorin / "index.theme").is_file()
    assert (blue / "index.theme").is_file()
    assert sum(1 for p in zorin.rglob("*") if p.is_file()) > 8000
    assert sum(1 for p in blue.rglob("*") if p.is_file()) > 1600
    blue_index = (blue / "index.theme").read_text(encoding="utf-8")
    assert "Inherits=Zorin,Adwaita,gnome,hicolor" in blue_index


def test_graphical_stack_selects_zorin_theme_and_icons():
    source = Path("src/xaac_thin_client_os/graphical_stack.py").read_text(encoding="utf-8")
    assert "gtk-theme-name=ZorinBlue-Light" in source
    assert "gtk-icon-theme-name=ZorinBlue-Light" in source


def test_exact_zorin_gtk_snapshot_is_vendored_and_installed():
    project_root = Path(".")
    theme = project_root / "assets/zorin-theme/ZorinBlue-Light"
    assert (theme / "index.theme").is_file()
    assert (theme / "gtk-3.0/gtk.css").is_file()
    assert (theme / "gtk-4.0/gtk.css").is_file()
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert 'assets/zorin-theme/ZorinBlue-Light' in source
    assert '/usr/share/themes/ZorinBlue-Light' in source
