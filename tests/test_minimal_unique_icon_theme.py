from pathlib import Path


def test_unique_minimal_icon_theme_is_exactly_twelve_svgs():
    root = Path("assets/zorin-icons/XAAC-Zorin-Light")
    assert (root / "index.theme").is_file()
    svgs = sorted(root.rglob("*.svg"))
    assert len(svgs) == 12
    assert not Path("assets/zorin-icons/ZorinBlue-Light").exists()
    assert "Name=XAAC-Zorin-Light" in (root / "index.theme").read_text(encoding="utf-8")


def test_graphical_stack_uses_unique_icon_theme_but_zorin_widget_theme():
    source = Path("src/xaac_thin_client_os/graphical_stack.py").read_text(encoding="utf-8")
    assert "gtk-theme-name=ZorinBlue-Light" in source
    assert "gtk-icon-theme-name=XAAC-Zorin-Light" in source
