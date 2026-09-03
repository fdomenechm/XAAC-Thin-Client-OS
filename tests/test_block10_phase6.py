from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

from xaac_thin_client_os.production_builder import ProductionIsoBuilder

ROOT = Path(__file__).parents[1]


def test_phase_10_6_assets_and_gate_exist() -> None:
    for path in (
        ROOT / "config/base-os-update.yaml",
        ROOT / "src/xaac_thin_client_os/base_os_update.py",
        ROOT / "assets/runtime/xaac_base_os_update_runtime.py",
        ROOT / "scripts/validate-block10-phase6.sh",
        ROOT / "docs/phases/block-10/phase-10-06.md",
    ):
        assert path.is_file()


def test_update_admin_exposes_controlled_base_os_commands() -> None:
    script = ROOT / "assets/runtime/xaac-update-admin"
    result = subprocess.run([str(script), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for command in ("os-status", "os-check", "os-update"):
        assert command in result.stdout


def test_os_update_confirmation_precedes_sudo_check() -> None:
    text = (ROOT / "assets/runtime/xaac-update-admin").read_text(encoding="utf-8")
    block = text[text.index('elif args.command == "os-update"'):]
    assert block.index("if not args.yes") < block.index("_require_root()")


def test_production_builder_installs_phase_10_6_after_component_update_architecture() -> None:
    configure = inspect.getsource(ProductionIsoBuilder.phase_configure)
    helper = inspect.getsource(ProductionIsoBuilder._configure_base_os_updates)
    assert "self._configure_update_architecture()" in configure
    assert "self._configure_base_os_updates()" in configure
    assert configure.index("self._configure_update_architecture()") < configure.index("self._configure_base_os_updates()")
    assert "assets/runtime/xaac_base_os_update_runtime.py" in helper
    assert "base-os-policy.json" in helper
    assert "apt-daily.timer" in helper


def test_production_sources_are_explicitly_signed_and_include_security() -> None:
    text = inspect.getsource(ProductionIsoBuilder._write_apt_sources)
    assert 'keyring = "/usr/share/keyrings/debian-archive-keyring.gpg"' in text
    assert "signed-by={keyring}" in text
    assert "suite}-updates" in text
    assert "suite}-security" in text
    assert "security.debian.org/debian-security" in text


def test_local_admin_has_base_os_update_commands() -> None:
    text = (ROOT / "config/local-admin.yaml").read_text(encoding="utf-8")
    assert "/usr/local/sbin/xaac-update-admin os-status" in text
    assert "/usr/local/sbin/xaac-update-admin os-check" in text
    assert "/usr/local/sbin/xaac-update-admin os-update --yes" in text


def test_release_gate_includes_phase_10_6() -> None:
    gate = (ROOT / "scripts/validate-block10-release.sh").read_text(encoding="utf-8")
    assert "validate-block10-phase6.sh" in gate
    assert "xaac_base_os_update_runtime.py" in gate
