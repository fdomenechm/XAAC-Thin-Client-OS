from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import yaml

from xaac_thin_client_os.production_builder import BuildPaths, ProductionIsoBuilder


ROOT = Path(__file__).resolve().parents[1]


EXPECTED = {
    "xaac-thin-client-package.yaml": ("xaac-thinclient", "1.1.0", "all"),
    "xaac-thin-client-vpn-package.yaml": ("xaac-thin-client-vpn", "1.1.0", "all"),
    "xaac-thin-client-network-package.yaml": ("xaac-thin-client-network", "1.1.0-1", "all"),
    "xaac-thin-client-dock-package.yaml": ("xaac-thin-client-dock", "1.1.0", "all"),
    "xaac-agent-package.yaml": ("xaac-agent", "1.1.0-1", "amd64"),
}


def test_xaac_110_profiles_match_embedded_debian_artifacts() -> None:
    for profile_name, expected in EXPECTED.items():
        profile = yaml.safe_load((ROOT / "config" / profile_name).read_text(encoding="utf-8"))
        package = profile["package"]
        artifact = ROOT / package["artifact"]
        assert artifact.is_file()
        result = subprocess.run(
            [
                "dpkg-deb",
                "--show",
                "--showformat=${Package}\n${Version}\n${Architecture}\n",
                str(artifact),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert tuple(result.stdout.splitlines()[:3]) == expected
        assert package["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()


def test_production_builder_requires_complete_xaac_110_component_set() -> None:
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(ROOT)  # type: ignore[misc]
    versions = builder._validate_required_component_artifacts()
    assert versions == {
        "xaac-thinclient": "1.1.0",
        "xaac-thin-client-vpn": "1.1.0",
        "xaac-thin-client-network": "1.1.0-1",
        "xaac-thin-client-dock": "1.1.0",
        "xaac-agent": "1.1.0-1",
    }


def test_kiosk_boot_orders_network_then_vpn_without_network_online_gate() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert 'configure-enable-xaac-network' in source
    assert 'Before=xaac-vpn-manager.service' in source
    assert '"Wants=\\n"' in source and '"After=\\n"' in source
    assert 'Wants=xaac-network-manager.service' in source
    assert 'After=dbus.service NetworkManager.service xaac-network-manager.service' in source
    assert 'Wants=xaac-network-manager.service xaac-vpn-manager.service' in source
    assert 'After=xaac-network-manager.service xaac-vpn-manager.service' in source
    assert 'configure-verify-xaac-connectivity-startup-order' in source
