from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_component_profiles_use_dedicated_configuration_roots() -> None:
    expected = {
        "xaac-thin-client-network-package.yaml": "/etc/xaac-network/xaac-network.ini",
        "xaac-thin-client-vpn-package.yaml": "/etc/xaac-vpn/vpn-manager.toml",
        "xaac-thin-client-dock-package.yaml": "/etc/xaac-dock/xaac-thin-client-dock.ini",
    }
    for filename, path in expected.items():
        profile = yaml.safe_load((ROOT / "config" / filename).read_text(encoding="utf-8"))
        assert profile["runtime"]["configuration_path"] == path

    launcher = yaml.safe_load(
        (ROOT / "config/thin-client-launcher.yaml").read_text(encoding="utf-8")
    )
    assert launcher["application"]["configuration_directory"] == "/etc/xaac-remote"

    agent = yaml.safe_load(
        (ROOT / "config/xaac-agent-package.yaml").read_text(encoding="utf-8")
    )
    assert agent["ownership"]["configuration_root"] == "/etc/xaac-agent"


def test_production_builder_normalises_legacy_package_paths() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(
        encoding="utf-8"
    )
    for path in ("/etc/xaac-network", "/etc/xaac-vpn", "/etc/xaac-remote", "/etc/xaac-dock"):
        assert path in source
    assert "ln -s /etc/xaac-remote /etc/xaac-thinclient" in source
    assert "xaac-component-config-layout.service" in source
    assert "ExecStart=/usr/bin/xaac-network-manager --config " in source
    assert "/etc/xaac-network/xaac-network.ini" in source
    assert "--config /etc/xaac-vpn/vpn-manager.toml" in source
    assert "ReadWritePaths=/etc/xaac-vpn" in source


def test_vpn_admin_uses_canonical_vpn_configuration() -> None:
    source = (ROOT / "assets/runtime/xaac-vpn-admin").read_text(encoding="utf-8")
    assert 'CONFIG_PATH = Path("/etc/xaac-vpn/vpn-manager.toml")' in source
    assert "/etc/xaac/vpn-manager.toml" not in source


def test_component_layout_runtime_is_posix_shell(tmp_path: Path) -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(
        encoding="utf-8"
    )
    marker = "runtime = r'''#!/bin/sh"
    start = source.index(marker) + len("runtime = r'''")
    end = source.index("'''", start)
    script = tmp_path / "xaac-component-config-layout"
    script.write_text(source[start:end], encoding="utf-8")
    result = subprocess.run(
        ["sh", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
