from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _extract(package: Path, target: Path) -> None:
    subprocess.run(["dpkg-deb", "-x", str(package), str(target)], check=True)


def test_corrected_vpn_package_contains_busy_cursor_and_button_lock(tmp_path: Path) -> None:
    package = ROOT / "packages/xaac-thin-client-vpn_1.1.0_all.deb"
    target = tmp_path / "vpn"
    _extract(package, target)
    source = next(target.glob("usr/lib/python3/dist-packages/xaac_thin_client_vpn/ui/main_window.py"))
    text = source.read_text(encoding="utf-8")
    assert 'set_cursor_from_name("wait" if busy else None)' in text
    assert "self._connect_button.set_sensitive(False)" in text
    assert "self._skip_button.set_sensitive(False)" in text
    assert "self._set_operation_busy(True)" in text
    assert "threading.Thread(" in text
    assert "target=self._disconnect_in_worker" in text
    assert "GLib.idle_add(self._complete_skip_from_idle)" in text


def test_corrected_thinclient_package_keeps_connection_busy_feedback_and_delegates_global_actions(tmp_path: Path) -> None:
    package = ROOT / "packages/xaac-thinclient_1.1.0_all.deb"
    target = tmp_path / "thinclient"
    _extract(package, target)
    source = next(target.glob("usr/lib/python3/dist-packages/xaac_thinclient/ui/login_window.py"))
    text = source.read_text(encoding="utf-8")
    assert 'self.set_cursor_from_name("wait" if busy else None)' in text
    assert "self.connect_button.set_sensitive(False)" in text
    assert "self.set_default_size(520, 460)" in text
    assert "self.about_button" not in text
    assert "self.diagnostic_button" not in text
    assert "self.power_button" not in text
    assert "request_poweroff" not in text


def test_dock_package_owns_about_diagnostics_and_shutdown_global_actions(tmp_path: Path) -> None:
    package = ROOT / "packages/xaac-thin-client-dock_1.1.0_all.deb"
    target = tmp_path / "dock"
    _extract(package, target)
    source = next(target.glob("usr/lib/python3/dist-packages/xaac_thin_client_dock/presentation/gtk_view.py"))
    text = source.read_text(encoding="utf-8")
    model = next(target.glob("usr/lib/python3/dist-packages/xaac_thin_client_dock/presentation/model.py"))
    model_text = model.read_text(encoding="utf-8")
    assert 'about_button.add_css_class("xaac-dock-brand-button")' in text
    assert 'diagnostics_button.add_css_class("xaac-dock-diagnostics-button")' in text
    assert 'power_button.add_css_class("xaac-dock-power-button")' in text
    assert 'gettext_message("About XAAC")' in text
    assert 'gettext_message("Diagnostics")' in text
    assert text.index("system_actions.append(diagnostics_button)") < text.index("system_actions.append(power_button)")
    assert "default_height: int = 96" in model_text
