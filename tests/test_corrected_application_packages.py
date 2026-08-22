from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _extract(package: Path, target: Path) -> None:
    subprocess.run(["dpkg-deb", "-x", str(package), str(target)], check=True)


def test_corrected_vpn_package_contains_busy_cursor_and_button_lock(tmp_path: Path) -> None:
    package = ROOT / "packages/xaac-thin-client-vpn_1.0.0_all.deb"
    target = tmp_path / "vpn"
    _extract(package, target)
    source = next(target.glob("usr/lib/python3/dist-packages/xaac_thin_client_vpn/ui/main_window.py"))
    text = source.read_text(encoding="utf-8")
    assert 'set_cursor_from_name("wait" if busy else None)' in text
    assert "self._connect_button.set_sensitive(False)" in text


def test_corrected_thinclient_package_contains_busy_cursor_and_button_lock(tmp_path: Path) -> None:
    package = ROOT / "packages/xaac-thinclient_1.0.0_all.deb"
    target = tmp_path / "thinclient"
    _extract(package, target)
    source = next(target.glob("usr/lib/python3/dist-packages/xaac_thinclient/ui/login_window.py"))
    text = source.read_text(encoding="utf-8")
    assert 'self.set_cursor_from_name("wait")' in text
    assert "self.connect_button.set_sensitive(False)" in text
