from pathlib import Path


def test_fast_visual_test_has_strict_icon_preflight():
    text = Path("scripts/test-zorin-visuals.sh").read_text(encoding="utf-8")
    assert "check-zorin-icon-resolution.py" in text
    assert 'XDG_CONFIG_HOME="$SANDBOX/config"' in text
    assert 'XDG_DATA_HOME="$SANDBOX/data"' in text
    assert 'XDG_DATA_DIRS="$SANDBOX/data:/usr/local/share:/usr/share"' in text
    assert 'GTK_THEME="ZorinBlue-Light"' in text


def test_icon_probe_checks_all_xaac_owned_icons_are_sandbox_local():
    text = Path("tools/check-zorin-icon-resolution.py").read_text(encoding="utf-8")
    expected = [
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
    ]
    for name in expected:
        assert name in text
    assert "path.relative_to(sandbox_icons)" in text
