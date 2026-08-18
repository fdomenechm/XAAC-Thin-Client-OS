from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_phase_10_3_is_integrated_in_production_builder() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "def _configure_maintenance_diagnostics" in source
    assert "self._configure_maintenance_diagnostics()" in source
    assert "assets/runtime/xaac-maintenance" in source
    assert "xaac_maintenance_runtime.py" in source
    assert "configure-maintenance-diagnostics-10-3" in source


def test_phase_10_3_local_admin_uses_canonical_maintenance_cli() -> None:
    source = (ROOT / "src/xaac_thin_client_os/local_admin.py").read_text(encoding="utf-8")
    assert "/usr/local/sbin/xaac-maintenance status" in source
    assert "/usr/local/sbin/xaac-maintenance diagnostics" in source
    assert "xaac-thin-client.service" not in source
    profile = yaml.safe_load((ROOT / "config/local-admin.yaml").read_text())
    assert "/usr/local/sbin/xaac-maintenance health" in profile["policy"]["sudo_commands"]
    assert "/usr/local/sbin/xaac/maintenance" not in "\n".join(profile["policy"]["sudo_commands"])


def test_phase_10_3_does_not_add_remote_management_channel() -> None:
    profile = yaml.safe_load((ROOT / "config/maintenance-diagnostics.yaml").read_text())
    serialized = str(profile).lower()
    assert "web" not in profile["commands"]
    assert "listen" not in serialized
    assert "server" not in serialized
    assert "socket" not in serialized


def test_phase_10_3_gate_exists_and_is_posix_shell() -> None:
    gate = ROOT / "scripts/validate-block10-phase3.sh"
    assert gate.is_file()
    text = gate.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert "pipefail" not in text
    assert "test_block10_phase3.py" in text
