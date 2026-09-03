from pathlib import Path
import configparser
import hashlib


EXPECTED_XAAC_ICON_SHA256 = {'auth-sim-symbolic': '01e42890afdc3082b248295d8a4ba61d91af8b836ee808f7fbfbd0002de4d9ae', 'computer-symbolic': 'cad86a1164bf8a8f2c7d568f0125d9899be9b9c02e0ef65420999a22124effa7', 'dialog-error-symbolic': '05a85ec0f73e64b10fc062e4bb0f20bcafbad028c85c18164b1bf045cbe4b4a2', 'dialog-warning-symbolic': '76e734f1e6492dc1c5ac46228a2320e5338bf7ad1c7c41118d7280ec79d0bc55', 'help-about-symbolic': 'b09b47be074be06f0bf4cde242233970cb99e30b8ac62e3d312b61389e8c8432', 'network-offline-symbolic': 'd024ef36a3c14303a2001aa587f80197d0ec2138fe84ad5e2a91b9d3a3e3bfdc', 'network-server-symbolic': 'f24cfc83fc059906e44bcd91f199f825a94685f059abd8e315a98c58389b1e22', 'network-transmit-receive-symbolic': '8ce73843ad3eed9b4792949bf7016526e2a2be20b30fea38c7fbe90d8a36c4a3', 'network-wired-symbolic': '274e8ae73d4e2da875f5963eae376ab56c0723df117614dce0701da88ef44270', 'system-search-symbolic': '4fca45d086d58b6f39a477706668487a7a86740ec9859018b0ccd3608a54065e', 'system-shutdown-symbolic': '99f7a262eba6ca9dd4336f748f2d5eb31c357a8f97b60076736d27639fe408c7', 'utilities-system-monitor-symbolic': '0b6ae88a036b0978c3263bad85d4589b3f944ed240771dd46b46a2a274ecca0e'}

ICON_CATEGORIES = {'auth-sim-symbolic': 'devices', 'computer-symbolic': 'devices', 'dialog-error-symbolic': 'status', 'dialog-warning-symbolic': 'status', 'help-about-symbolic': 'actions', 'network-offline-symbolic': 'status', 'network-server-symbolic': 'devices', 'network-transmit-receive-symbolic': 'status', 'network-wired-symbolic': 'status', 'system-search-symbolic': 'actions', 'system-shutdown-symbolic': 'actions', 'utilities-system-monitor-symbolic': 'apps'}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_production_builder_installs_minimal_zorin_icon_subset():
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    section = source[source.index("def _install_zorin_icon_theme"):source.index("def _install_zorin_gtk_theme")]
    assert 'assets/zorin-icons/XAAC-Zorin-Light' in section
    assert '/usr/share/icons/XAAC-Zorin-Light' in section
    assert 'shutil.copytree(source, destination, symlinks=False)' in section
    assert '("Zorin", "ZorinBlue-Light")' not in section
    assert 'urlretrieve' not in section


def test_minimal_theme_contains_only_exact_xaac_icons():
    theme = Path("assets/zorin-icons/XAAC-Zorin-Light")
    index = theme / "index.theme"
    assert index.is_file()
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(index, encoding="utf-8")
    assert parser["Icon Theme"]["Name"] == "XAAC-Zorin-Light"
    assert parser["Icon Theme"]["Inherits"] == "Adwaita,gnome,hicolor"
    directories = parser["Icon Theme"]["Directories"].split(",")
    assert directories == [
        "scalable/actions", "scalable/apps", "scalable/devices", "scalable/status"
    ]

    svg_files = sorted(theme.rglob("*.svg"))
    assert len(svg_files) == len(EXPECTED_XAAC_ICON_SHA256)
    assert {p.stem for p in svg_files} == set(EXPECTED_XAAC_ICON_SHA256)

    for name, expected_hash in EXPECTED_XAAC_ICON_SHA256.items():
        path = theme / "scalable" / ICON_CATEGORIES[name] / f"{name}.svg"
        assert path.is_file()
        assert not path.is_symlink()
        assert _sha256(path) == expected_hash


def test_icon_payload_is_small_and_has_no_unused_theme_tree():
    root = Path("assets/zorin-icons")
    payload = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    assert payload < 100_000
    assert not (root / "Zorin").exists()
    assert not any(p.is_symlink() for p in root.rglob("*"))


def test_graphical_stack_selects_zorin_theme_and_icons():
    source = Path("src/xaac_thin_client_os/graphical_stack.py").read_text(encoding="utf-8")
    assert "gtk-theme-name=ZorinBlue-Light" in source
    assert "gtk-icon-theme-name=XAAC-Zorin-Light" in source


def test_exact_zorin_gtk_snapshot_is_vendored_and_installed():
    theme = Path("assets/zorin-theme/ZorinBlue-Light")
    assert (theme / "index.theme").is_file()
    assert (theme / "gtk-3.0/gtk.css").is_file()
    assert (theme / "gtk-4.0/gtk.css").is_file()
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert 'assets/zorin-theme/ZorinBlue-Light' in source
    assert '/usr/share/themes/ZorinBlue-Light' in source

def test_kiosk_gtk_settings_follow_session_xdg_config_home():
    graphical = Path("config/graphical-stack.yaml").read_text(encoding="utf-8")
    session = Path("src/xaac_thin_client_os/session_manager.py").read_text(encoding="utf-8")
    assert "export XDG_CONFIG_HOME=/etc/xaac" in session
    assert "gtk3_settings_file: /etc/xaac/gtk-3.0/settings.ini" in graphical
    assert "gtk4_settings_file: /etc/xaac/gtk-4.0/settings.ini" in graphical

