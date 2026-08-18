from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_phase_10_4_is_integrated_in_production_builder() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "def _configure_recovery_environment" in source
    assert "self._configure_recovery_environment()" in source
    assert "assets/runtime/xaac-recovery" in source
    assert "xaac_recovery_runtime.py" in source
    assert "configure-recovery-environment-10-4" in source


def test_recovery_boot_keeps_normal_grub_hidden_but_interruptible() -> None:
    policy = yaml.safe_load((ROOT / "config/recovery-environment.yaml").read_text(encoding="utf-8"))
    assert policy["boot"]["hidden_menu_timeout_seconds"] == 1
    source = (ROOT / "src/xaac_thin_client_os/recovery_environment.py").read_text(encoding="utf-8")
    assert "GRUB_TIMEOUT_STYLE=hidden" in source
    assert "42_xaac_recovery" not in source or "grub_entry" in source


def test_recovery_does_not_enable_factory_reset_or_remote_channel() -> None:
    policy = yaml.safe_load((ROOT / "config/recovery-environment.yaml").read_text(encoding="utf-8"))
    assert policy["factory_reset"]["enabled"] is False
    assert policy["safety"]["automatic_factory_reset"] is False
    assert policy["safety"]["remote_unattended_factory_reset"] is False
    serialized = str(policy).lower()
    assert "listen" not in serialized
    assert "socket" not in serialized


def test_local_admin_policy_knows_recovery_commands() -> None:
    profile = yaml.safe_load((ROOT / "config/local-admin.yaml").read_text(encoding="utf-8"))
    commands = profile["policy"]["sudo_commands"]
    assert "/usr/local/sbin/xaac-recovery status" in commands
    assert "/usr/local/sbin/xaac-recovery rollback --yes" in commands
    assert "/usr/local/sbin/xaac-recovery repair --yes" in commands
    assert "/usr/local/sbin/xaac-recovery repair --restore-configuration --yes" in commands


def test_phase_10_4_gate_exists_and_is_posix_shell() -> None:
    gate = ROOT / "scripts/validate-block10-phase4.sh"
    assert gate.is_file()
    text = gate.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert "pipefail" not in text
    assert "test_block10_phase4.py" in text
    assert "test_recovery_runtime_phase10.py" in text


def test_recovery_login_flow_does_not_fix_username_and_non_admin_accounts_stay_locked() -> None:
    recovery = (ROOT / "src/xaac_thin_client_os/recovery_environment.py").read_text(encoding="utf-8")
    builder = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "agetty -o '-p -- \\\\\\\\u' --noissue - linux" in recovery
    assert "--noreset" not in recovery
    assert "--noclear" not in recovery
    assert "systemd.show_status=0" in recovery
    assert "plymouth.enable=0" in recovery
    assert "--login-program" not in recovery
    assert "exec /bin/login xaac-admin" not in recovery
    assert '["passwd", "--lock", "root"]' in builder
    assert '["passwd", "--lock", "xaac-kiosk"]' in builder
    assert '["usermod", "--shell", "/usr/sbin/nologin", "xaac-kiosk"]' in builder
