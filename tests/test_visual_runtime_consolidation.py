from pathlib import Path

def test_visual_test_caches_unique_theme():
    t=Path("scripts/test-zorin-visuals.sh").read_text()
    assert '$SANDBOX/data/icons/XAAC-Zorin-Light' in t
    assert '$SANDBOX/data/icons/ZorinBlue-Light' not in t

def test_runtime_uses_validated_icon_theme():
    g=Path("src/xaac_thin_client_os/graphical_stack.py").read_text()
    b=Path("src/xaac_thin_client_os/production_builder.py").read_text()
    assert "gtk-theme-name=ZorinBlue-Light" in g
    assert "gtk-icon-theme-name=XAAC-Zorin-Light" in g
    assert "/usr/share/icons/XAAC-Zorin-Light" in b
