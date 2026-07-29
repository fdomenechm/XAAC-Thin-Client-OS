from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.systemd_hardening import (
    SystemdHardeningError,
    SystemdHardeningInstaller,
    create_systemd_hardening_plan,
    load_systemd_hardening,
)


PROFILE = Path("config/systemd-hardening.yaml")


def test_profile_loads_and_covers_required_controls() -> None:
    profile = load_systemd_hardening(PROFILE)
    assert profile["defaults"]["no_new_privileges"] is True
    assert profile["defaults"]["protect_system"] == "strict"
    assert profile["defaults"]["device_policy"] == "closed"
    assert len(profile["services"]) == 4


def test_plan_rejects_unsafe_rootfs(tmp_path: Path) -> None:
    with pytest.raises(SystemdHardeningError, match="Rootfs insegur"):
        create_systemd_hardening_plan(tmp_path, PROFILE)


def test_duplicate_units_are_rejected(tmp_path: Path) -> None:
    data = yaml.safe_load(PROFILE.read_text())
    data["services"].append(dict(data["services"][0]))
    profile = tmp_path / "policy.yaml"
    profile.write_text(yaml.safe_dump(data))
    with pytest.raises(SystemdHardeningError, match="duplicada"):
        load_systemd_hardening(profile)


def test_disabled_mandatory_control_is_rejected(tmp_path: Path) -> None:
    data = yaml.safe_load(PROFILE.read_text())
    data["defaults"]["no_new_privileges"] = False
    profile = tmp_path / "policy.yaml"
    profile.write_text(yaml.safe_dump(data))
    with pytest.raises(SystemdHardeningError, match="desactivat"):
        load_systemd_hardening(profile)


def test_unsafe_writable_path_is_rejected(tmp_path: Path) -> None:
    data = yaml.safe_load(PROFILE.read_text())
    data["services"][0]["writable_paths"] = ["/var/lib/../etc"]
    profile = tmp_path / "policy.yaml"
    profile.write_text(yaml.safe_dump(data))
    with pytest.raises(SystemdHardeningError, match="Ruta insegura"):
        load_systemd_hardening(profile)


def test_install_writes_dropins_policy_and_state(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    plan = create_systemd_hardening_plan(rootfs, PROFILE)
    paths = SystemdHardeningInstaller().install(plan)
    assert len(paths) == 6
    content = plan.dropin("xaac-agent.service").read_text()
    assert "NoNewPrivileges=yes" in content
    assert "ProtectSystem=strict" in content
    assert "CapabilityBoundingSet=CAP_NET_ADMIN" in content
    assert "SystemCallFilter=@system-service ~@mount ~@reboot ~@swap" in content
    state = json.loads(plan.destination("state").read_text())
    assert state["service_count"] == 4
    assert state["least_privilege"] is True


def test_device_allow_is_service_specific(tmp_path: Path) -> None:
    plan = create_systemd_hardening_plan(tmp_path / "rootfs", PROFILE)
    SystemdHardeningInstaller().install(plan)
    rustdesk = plan.dropin("xaac-rustdesk.service").read_text()
    agent = plan.dropin("xaac-agent.service").read_text()
    assert "DeviceAllow=/dev/uinput rw" in rustdesk
    assert "DeviceAllow=" not in agent


def test_install_is_idempotent(tmp_path: Path) -> None:
    plan = create_systemd_hardening_plan(tmp_path / "rootfs", PROFILE)
    installer = SystemdHardeningInstaller()
    installer.install(plan)
    before = {path: path.read_bytes() for path in installer.install(plan, dry_run=True)}
    installer.install(plan)
    assert before == {path: path.read_bytes() for path in before}


def test_symlink_destination_is_rejected(tmp_path: Path) -> None:
    plan = create_systemd_hardening_plan(tmp_path / "rootfs", PROFILE)
    target = plan.destination("policy")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(SystemdHardeningError, match="enllaç simbòlic"):
        SystemdHardeningInstaller().install(plan)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_systemd_hardening_plan(tmp_path / "rootfs", PROFILE)
    paths = SystemdHardeningInstaller().install(plan, dry_run=True)
    assert all(not path.exists() for path in paths)


def test_cli_exposes_systemd_hardening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = build_parser().parse_args(["configure-systemd-hardening", "--dry-run"])
    assert args.command == "configure-systemd-hardening"
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    (root / "config/systemd-hardening.yaml").write_bytes(PROFILE.read_bytes())
    assert main(["--root", str(root), "configure-systemd-hardening", "--dry-run"]) == 0
