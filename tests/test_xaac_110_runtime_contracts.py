from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb required")


def _extract(project_root: Path, tmp_path: Path, package: str) -> Path:
    root = tmp_path / package
    subprocess.run(
        ["dpkg-deb", "-x", str(project_root / "packages" / package), str(root)],
        check=True,
    )
    return root


def test_embedded_dock_uses_real_network_vpn_contracts_and_canonical_config(
    project_root: Path, tmp_path: Path
) -> None:
    root = _extract(project_root, tmp_path, "xaac-thin-client-dock_1.1.0_all.deb")
    package = root / "usr/lib/python3/dist-packages/xaac_thin_client_dock"
    network = (package / "integrations/network.py").read_text(encoding="utf-8")
    vpn = (package / "integrations/vpn.py").read_text(encoding="utf-8")
    flow = (package / "integrations/flow.py").read_text(encoding="utf-8")

    assert "Gio.BusType.SYSTEM" in network
    assert 'VPN_DBUS_NAME = "org.xaac.ThinClient.VpnManager1"' in vpn
    assert 'return self._call_json("GetCapabilities")' not in vpn  # policy is normalised
    assert 'capabilities = self._call_json("GetCapabilities")' in vpn
    assert 'return self._call_json("GetStatus")' in vpn
    assert "return self.delegate.launch(component_id)" in flow
    assert (root / "etc/xaac-dock/xaac-thin-client-dock.ini").is_file()


def test_embedded_remote_exposes_dock_state_contract_and_canonical_config(
    project_root: Path, tmp_path: Path
) -> None:
    root = _extract(project_root, tmp_path, "xaac-thinclient_1.1.0_all.deb")
    state_service = (
        root
        / "usr/lib/python3/dist-packages/xaac_thinclient/ipc/state_service.py"
    ).read_text(encoding="utf-8")

    assert 'REMOTE_DBUS_NAME = "org.xaac.ThinClient"' in state_service
    assert 'REMOTE_DBUS_INTERFACE = "org.xaac.ThinClient1"' in state_service
    assert 'Gio.BusType.SESSION' in state_service
    assert 'method_name == "GetState"' in state_service
    assert (root / "etc/xaac-remote/config.ini").is_file()
    assert not (root / "etc/xaac-thinclient").exists()
