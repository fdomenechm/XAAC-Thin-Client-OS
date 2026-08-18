from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaac_thin_client_os.recovery_environment import (
    RecoveryEnvironmentError,
    RecoveryEnvironmentInstaller,
    create_recovery_environment_plan,
    load_recovery_environment,
)

ROOT = Path(__file__).parents[1]


def _rootfs(tmp_path: Path) -> Path:
    root = tmp_path / ".build" / "rootfs"
    root.mkdir(parents=True)
    return root


def _altered(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "recovery-environment.yaml"
    path.write_text(
        (ROOT / "config/recovery-environment.yaml").read_text(encoding="utf-8").replace(
            old, new
        ),
        encoding="utf-8",
    )
    return path


def test_loads_phase_10_4_policy() -> None:
    policy = load_recovery_environment(ROOT / "config/recovery-environment.yaml")
    assert policy["phase"] == "10.4"
    assert policy["boot"]["network_default"] == "disabled"
    assert policy["factory_reset"]["enabled"] is False
    assert policy["commands"] == ["status", "rollback", "repair", "network-on", "network-off"]


def test_manifest_is_stable(tmp_path: Path) -> None:
    plan = create_recovery_environment_plan(
        _rootfs(tmp_path), ROOT / "config/recovery-environment.yaml"
    )
    assert plan.manifest() == {
        "schema_version": 1,
        "recovery_id": "xaac-recovery",
        "phase": "10.4",
        "hardware_profile": "wyse3040",
        "commands": ["status", "rollback", "repair", "network-on", "network-off"],
        "factory_reset_enabled": False,
        "network_default": "disabled",
    }


def test_installer_creates_minimal_target_and_grub_entry(tmp_path: Path) -> None:
    plan = create_recovery_environment_plan(
        _rootfs(tmp_path), ROOT / "config/recovery-environment.yaml"
    )
    policy, state, target, console, console_login, grub_entry, grub_defaults, tmpfiles = (
        RecoveryEnvironmentInstaller().install(plan)
    )
    assert json.loads(policy.read_text())["safety"]["fail_closed"] is True
    assert json.loads(state.read_text())["status"] == "ready"
    assert "xaac-recovery-console.service" in target.read_text()
    assert "getty@tty1.service" not in target.read_text()
    console_text = console.read_text()
    assert "ConditionKernelCommandLine=systemd.unit=xaac-recovery.target" in console_text
    assert "--login-program /usr/local/libexec/xaac/recovery-admin-login tty1 linux" in console_text
    assert console_login.read_text() == "#!/bin/sh\nset -eu\nexec /bin/login xaac-admin\n"
    assert "Conflicts=getty@tty1.service" in console_text
    assert "Conflicts=graphical.target greetd.service xaac-vpn-manager.service xaac-agent.service" in target.read_text()
    assert "systemd.unit=xaac-recovery.target" in grub_entry.read_text()
    assert "root=LABEL=XAAC_ROOT" in grub_entry.read_text()
    assert "GRUB_TIMEOUT=1" in grub_defaults.read_text()
    assert "GRUB_TIMEOUT_STYLE=hidden" in grub_defaults.read_text()
    assert "d /var/log/xaac-recovery 0750 root root" in tmpfiles.read_text()
    assert [path.stat().st_mode & 0o777 for path in (policy, state, target, console, console_login, grub_entry, grub_defaults, tmpfiles)] == [
        0o640,
        0o640,
        0o644,
        0o644,
        0o755,
        0o750,
        0o644,
        0o644,
    ]


def test_installer_is_idempotent(tmp_path: Path) -> None:
    plan = create_recovery_environment_plan(
        _rootfs(tmp_path), ROOT / "config/recovery-environment.yaml"
    )
    installer = RecoveryEnvironmentInstaller()
    paths = installer.install(plan)
    before = tuple(path.read_bytes() for path in paths)
    installer.install(plan)
    assert before == tuple(path.read_bytes() for path in paths)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_recovery_environment_plan(
        _rootfs(tmp_path), ROOT / "config/recovery-environment.yaml"
    )
    paths = RecoveryEnvironmentInstaller().install(plan, dry_run=True)
    assert len(paths) == 8
    assert not any(path.exists() for path in paths)


def test_rejects_factory_reset_enablement(tmp_path: Path) -> None:
    with pytest.raises(RecoveryEnvironmentError, match="Factory reset"):
        load_recovery_environment(_altered(tmp_path, "enabled: false", "enabled: true"))


def test_rejects_zero_grub_timeout(tmp_path: Path) -> None:
    with pytest.raises(RecoveryEnvironmentError, match="Timeout"):
        load_recovery_environment(
            _altered(tmp_path, "hidden_menu_timeout_seconds: 1", "hidden_menu_timeout_seconds: 0")
        )


def test_rejects_network_enabled_by_default(tmp_path: Path) -> None:
    with pytest.raises(RecoveryEnvironmentError, match="xarxa ni quiosc"):
        load_recovery_environment(
            _altered(tmp_path, "network_default: disabled", "network_default: enabled")
        )


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    plan = create_recovery_environment_plan(
        _rootfs(tmp_path), ROOT / "config/recovery-environment.yaml"
    )
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(RecoveryEnvironmentError, match="enllaç simbòlic"):
        RecoveryEnvironmentInstaller().install(plan)


def test_recovery_console_is_independent_from_masked_normal_tty1(tmp_path: Path) -> None:
    """Recovery must not depend on the tty1 getty masked by the installed kiosk."""
    plan = create_recovery_environment_plan(
        _rootfs(tmp_path), ROOT / "config/recovery-environment.yaml"
    )
    _, _, target, console, console_login, *_ = RecoveryEnvironmentInstaller().install(plan)
    production_source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(
        encoding="utf-8"
    )
    assert 'ln -sfn /dev/null "$mount_root/etc/systemd/system/getty@tty1.service"' in production_source
    assert "getty@tty1.service" not in target.read_text(encoding="utf-8")
    assert "xaac-recovery-console.service" in target.read_text(encoding="utf-8")
    assert "Conflicts=getty@tty1.service" in console.read_text(encoding="utf-8")
    assert "exec /bin/login xaac-admin" in console_login.read_text(encoding="utf-8")
