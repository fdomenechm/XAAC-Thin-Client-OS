from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_openvpn3_uses_offline_resolv_conf_configuration_in_chroot() -> None:
    source = (
        ROOT / "src/xaac_thin_client_os/production_builder.py"
    ).read_text(encoding="utf-8")

    assert "openvpn3-admin init-config --write-configs --force" in source
    assert "test -s /var/lib/openvpn3/netcfg.json" in source
    assert "grep -F '/etc/resolv.conf' /var/lib/openvpn3/netcfg.json" in source
    assert "configure-openvpn3-netcfg" in source

    # These commands require net.openvpn.v3.netcfg over D-Bus and therefore
    # must never be executed inside the build chroot.
    assert "openvpn3-admin netcfg-service --config-set" not in source
    assert "openvpn3-admin netcfg-service --config-unset" not in source
    assert "openvpn3-admin netcfg-service --config-show" not in source


def test_vpn_admin_config_is_root_owned() -> None:
    source = (
        ROOT / "src/xaac_thin_client_os/production_builder.py"
    ).read_text(encoding="utf-8")
    assert "chown root:root /etc/xaac/vpn-manager.toml" in source
    assert "chmod 0644 /etc/xaac/vpn-manager.toml" in source
