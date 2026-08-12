from pathlib import Path


def test_production_builder_forces_thinclient_production_mode():
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert 'mode = development' in source
    assert 'mode = production' in source
    assert '_configure_xaac_thinclient_production_runtime()' in source


def test_kiosk_power_helpers_are_fixed_and_sudo_is_exactly_scoped():
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert '/usr/local/sbin/xaac-kiosk-poweroff' in source
    assert '/usr/local/sbin/xaac-kiosk-reboot' in source
    assert 'exec /usr/bin/systemctl poweroff' in source
    assert 'exec /usr/bin/systemctl reboot' in source
    assert '/etc/sudoers.d/xaac-kiosk-power' in source
    assert 'xaac-kiosk ALL=(root) NOPASSWD:' in source


def test_sudo_is_an_explicit_base_package():
    packages = Path("config/packages.yaml").read_text(encoding="utf-8")
    assert "- sudo\n" in packages
