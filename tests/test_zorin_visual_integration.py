from pathlib import Path
import configparser


EXPECTED_XAAC_ICONS = {
    "auth-sim-symbolic",
    "computer-symbolic",
    "dialog-error-symbolic",
    "dialog-warning-symbolic",
    "help-about-symbolic",
    "network-offline-symbolic",
    "network-server-symbolic",
    "network-transmit-receive-symbolic",
    "network-wired-symbolic",
    "system-search-symbolic",
    "system-shutdown-symbolic",
    "utilities-system-monitor-symbolic",
}


def _theme_icon_names(theme: Path) -> set[str]:
    names: set[str] = set()
    for path in theme.rglob("*.svg"):
        names.add(path.stem)
    return names


def test_production_builder_installs_minimal_zorin_icon_subset():
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    section = source[source.index("def _install_zorin_icon_theme"):source.index("def _install_zorin_gtk_theme")]
    assert 'assets/zorin-icons/ZorinBlue-Light' in section
    assert '/usr/share/icons/ZorinBlue-Light' in section
    assert 'shutil.copytree(source, destination, symlinks=True)' in section
    assert '("Zorin", "ZorinBlue-Light")' not in section
    assert 'urlretrieve' not in section


def test_minimal_theme_preserves_categories_aliases_and_fallbacks():
    theme = Path("assets/zorin-icons/ZorinBlue-Light")
    index = theme / "index.theme"
    assert index.is_file()
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(index, encoding="utf-8")
    assert parser["Icon Theme"]["Name"] == "ZorinBlue-Light"
    assert parser["Icon Theme"]["Inherits"] == "Adwaita,gnome,hicolor"
    directories = parser["Icon Theme"]["Directories"].split(",")
    assert directories == [
        "scalable/actions", "scalable/apps", "scalable/devices", "scalable/status"
    ]
    for directory in directories:
        assert (theme / directory).is_dir()
        assert directory in parser

    # All 12 application icon names resolve directly in this theme.
    names = _theme_icon_names(theme)
    assert EXPECTED_XAAC_ICONS <= names

    # Symbolic aliases used by the original Zorin theme remain valid.
    for alias in (
        theme / "scalable/devices/computer-symbolic.svg",
        theme / "scalable/actions/help-about-symbolic.svg",
        theme / "scalable/status/network-offline-symbolic.svg",
        theme / "scalable/actions/system-search-symbolic.svg",
    ):
        assert alias.is_symlink()
        assert alias.resolve().is_file()


def test_icon_payload_is_small():
    root = Path("assets/zorin-icons")
    payload = sum(p.lstat().st_size for p in root.rglob("*") if p.is_file() or p.is_symlink())
    assert payload < 100_000
    assert not (root / "Zorin").exists()


def test_graphical_stack_selects_zorin_theme_and_icons():
    source = Path("src/xaac_thin_client_os/graphical_stack.py").read_text(encoding="utf-8")
    assert "gtk-theme-name=ZorinBlue-Light" in source
    assert "gtk-icon-theme-name=ZorinBlue-Light" in source


def test_exact_zorin_gtk_snapshot_is_vendored_and_installed():
    theme = Path("assets/zorin-theme/ZorinBlue-Light")
    assert (theme / "index.theme").is_file()
    assert (theme / "gtk-3.0/gtk.css").is_file()
    assert (theme / "gtk-4.0/gtk.css").is_file()
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert 'assets/zorin-theme/ZorinBlue-Light' in source
    assert '/usr/share/themes/ZorinBlue-Light' in source
