from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_openvpn3_uses_resolv_conf_backend() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "openvpn3-admin init-config --write-configs --force" in source
    assert "--config-unset systemd-resolved" in source
    assert "--config-set resolv-conf /etc/resolv.conf" in source
    assert "configure-openvpn3-netcfg" in source


def test_vpn_admin_config_is_root_owned() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "chown root:root /etc/xaac/vpn-manager.toml" in source
    assert "chmod 0644 /etc/xaac/vpn-manager.toml" in source
