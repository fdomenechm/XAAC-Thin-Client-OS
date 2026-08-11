from pathlib import Path


EXPECTED_XAAC_ICONS = ['auth-sim-symbolic', 'computer-symbolic', 'dialog-error-symbolic', 'dialog-warning-symbolic', 'help-about-symbolic', 'network-offline-symbolic', 'network-server-symbolic', 'network-transmit-receive-symbolic', 'network-wired-symbolic', 'system-search-symbolic', 'system-shutdown-symbolic', 'utilities-system-monitor-symbolic']


def test_production_builder_installs_minimal_exact_icon_theme():
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert 'assets/xaac-zorin-exact-icons' in source
    assert '/usr/share/icons/XAAC-Zorin-Exact' in source
    assert 'assets/zorin-icons' not in source
    section = source[source.index("def _install_zorin_icon_theme"):source.index("def _install_zorin_gtk_theme")]
    assert 'urlretrieve' not in section


def test_vendored_icon_theme_contains_only_xaac_icons():
    root = Path("assets/xaac-zorin-exact-icons")
    assert (root / "index.theme").is_file()
    svg_names = sorted(p.stem for p in root.rglob("*.svg"))
    assert svg_names == EXPECTED_XAAC_ICONS
    assert len(svg_names) == 12
    assert sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) < 100_000


def test_graphical_stack_selects_zorin_gtk_and_exact_xaac_icons():
    source = Path("src/xaac_thin_client_os/graphical_stack.py").read_text(encoding="utf-8")
    assert "gtk-theme-name=ZorinBlue-Light" in source
    assert "gtk-icon-theme-name=XAAC-Zorin-Exact" in source


def test_exact_zorin_gtk_snapshot_is_vendored_and_installed():
    project_root = Path(".")
    theme = project_root / "assets/zorin-theme/ZorinBlue-Light"
    assert (theme / "index.theme").is_file()
    assert (theme / "gtk-3.0/gtk.css").is_file()
    assert (theme / "gtk-4.0/gtk.css").is_file()
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert 'assets/zorin-theme/ZorinBlue-Light' in source
    assert '/usr/share/themes/ZorinBlue-Light' in source
