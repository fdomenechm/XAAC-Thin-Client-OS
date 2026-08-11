from pathlib import Path


def test_fast_visual_test_uses_os_assets_and_isolated_xdg():
    text = Path("scripts/test-zorin-visuals.sh").read_text(encoding="utf-8")
    assert "assets/zorin-icons/ZorinBlue-Light" in text
    assert "assets/zorin-theme/ZorinBlue-Light" in text
    assert 'XDG_CONFIG_HOME="$SANDBOX/config"' in text
    assert 'XDG_DATA_HOME="$SANDBOX/data"' in text
    assert 'GTK_THEME="ZorinBlue-Light"' in text
    assert "build-production-iso" not in text
