from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.apparmor_configuration import (
    AppArmorError,
    AppArmorInstaller,
    create_apparmor_plan,
    load_apparmor_policy,
)
from xaac_thin_client_os.cli import build_parser, main

PROFILE = Path("config/apparmor.yaml")


def test_profile_loads_current_runtime_entrypoints_in_complain_mode() -> None:
    profile = load_apparmor_policy(PROFILE)
    assert profile["policy_id"] == "xaac-apparmor-v2"
    assert len(profile["profiles"]) == 3
    assert {item["mode"] for item in profile["profiles"]} == {"complain"}
    assert {item["executable"] for item in profile["profiles"]} == {
        "/usr/bin/xaac-agent",
        "/usr/bin/xaac-thinclient",
        "/usr/bin/xaac-thin-client-vpn",
    }
    assert profile["defaults"]["audit_denied"] is True


def test_unsafe_rootfs_rejected(tmp_path: Path) -> None:
    with pytest.raises(AppArmorError, match="Rootfs insegur"):
        create_apparmor_plan(tmp_path, PROFILE)


def test_duplicate_profile_rejected(tmp_path: Path) -> None:
    data = yaml.safe_load(PROFILE.read_text())
    data["profiles"].append(dict(data["profiles"][0]))
    file = tmp_path / "p.yaml"
    file.write_text(yaml.safe_dump(data))
    with pytest.raises(AppArmorError, match="duplicat"):
        load_apparmor_policy(file)


def test_unsafe_path_rejected(tmp_path: Path) -> None:
    data = yaml.safe_load(PROFILE.read_text())
    data["profiles"][0]["write_paths"] = ["/var/lib/../etc/**"]
    file = tmp_path / "p.yaml"
    file.write_text(yaml.safe_dump(data))
    with pytest.raises(AppArmorError, match="Ruta insegura"):
        load_apparmor_policy(file)


def test_invalid_mode_rejected(tmp_path: Path) -> None:
    data = yaml.safe_load(PROFILE.read_text())
    data["profiles"][0]["mode"] = "disabled"
    file = tmp_path / "p.yaml"
    file.write_text(yaml.safe_dump(data))
    with pytest.raises(AppArmorError, match="Mode AppArmor"):
        load_apparmor_policy(file)


def test_install_writes_current_profiles_complain_links_and_state(tmp_path: Path) -> None:
    plan = create_apparmor_plan(tmp_path / "rootfs", PROFILE)
    paths = AppArmorInstaller().install(plan)
    assert len(paths) == 8
    agent = plan.profile_path("usr.bin.xaac-agent").read_text()
    assert "profile usr.bin.xaac-agent /usr/bin/xaac-agent" in agent
    assert "capability net_admin," not in agent
    for name in ("usr.bin.xaac-agent", "usr.bin.xaac-thinclient", "usr.bin.xaac-thin-client-vpn"):
        link = plan.complain_link(name)
        assert link.is_symlink() and os.readlink(link) == f"../{name}"
    state = json.loads(plan.destination("state").read_text())
    assert state["enforce_count"] == 0
    assert state["complain_count"] == 3


def test_stale_historical_runtime_names_are_not_profiled(tmp_path: Path) -> None:
    plan = create_apparmor_plan(tmp_path / "rootfs", PROFILE)
    AppArmorInstaller().install(plan)
    assert not plan.profile_path("usr.sbin.xaac-agent").exists()
    assert not plan.profile_path("usr.bin.xaac-thin-client").exists()


def test_install_idempotent(tmp_path: Path) -> None:
    plan = create_apparmor_plan(tmp_path / "rootfs", PROFILE)
    installer = AppArmorInstaller()
    installer.install(plan)
    before = {
        path: (path.readlink() if path.is_symlink() else path.read_bytes())
        for path in installer.install(plan, dry_run=True)
    }
    installer.install(plan)
    after = {path: (path.readlink() if path.is_symlink() else path.read_bytes()) for path in before}
    assert before == after


def test_symlink_destination_rejected(tmp_path: Path) -> None:
    plan = create_apparmor_plan(tmp_path / "rootfs", PROFILE)
    target = plan.destination("policy")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(AppArmorError, match="enllaç simbòlic"):
        AppArmorInstaller().install(plan)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_apparmor_plan(tmp_path / "rootfs", PROFILE)
    paths = AppArmorInstaller().install(plan, dry_run=True)
    assert all(not path.exists() for path in paths)


def test_cli_exposes_apparmor(tmp_path: Path) -> None:
    assert build_parser().parse_args(["configure-apparmor", "--dry-run"]).command == "configure-apparmor"
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    (root / "config/apparmor.yaml").write_bytes(PROFILE.read_bytes())
    assert main(["--root", str(root), "configure-apparmor", "--dry-run"]) == 0
