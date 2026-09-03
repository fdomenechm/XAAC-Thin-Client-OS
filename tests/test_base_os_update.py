from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from xaac_thin_client_os.base_os_update import (
    BaseOsUpdateError,
    BaseOsUpdateInstaller,
    create_base_os_update_plan,
    load_base_os_update,
)

ROOT = Path(__file__).parents[1]
POLICY = ROOT / "config/base-os-update.yaml"


def _copy_policy(tmp_path: Path, replace: tuple[str, str] | None = None) -> Path:
    text = POLICY.read_text(encoding="utf-8")
    if replace is not None:
        text = text.replace(*replace)
    path = tmp_path / "base-os-update.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_phase_10_6_policy_is_debian13_trixie_only() -> None:
    policy = load_base_os_update(POLICY)
    assert policy["phase"] == "10.6"
    assert policy["platform"] == {
        "os_id": "xaac-thin-client-os",
        "debian_major": 13,
        "suite": "trixie",
        "architecture": "amd64",
    }
    suites = {suite for repo in policy["repositories"] for suite in repo["suites"]}
    assert suites == {"trixie", "trixie-updates", "trixie-security"}


def test_phase_10_6_policy_forbids_release_change_removal_downgrade_and_automatic_reboot() -> None:
    policy = load_base_os_update(POLICY)["policy"]
    assert policy["apt_operation"] == "upgrade-with-new-pkgs"
    assert policy["allow_release_change"] is False
    assert policy["allow_removals"] is False
    assert policy["allow_downgrade"] is False
    assert policy["automatic_reboot"] is False
    assert policy["automatic_rollback"] is False
    assert set(policy["protected_packages"]) == {
        "xaac-thinclient",
        "xaac-thin-client-vpn",
        "xaac-thin-client-network",
        "xaac-thin-client-dock",
        "xaac-agent",
    }


def test_phase_10_6_rejects_release_change(tmp_path: Path) -> None:
    path = _copy_policy(tmp_path, ("allow_release_change: false", "allow_release_change: true"))
    with pytest.raises(BaseOsUpdateError, match="protecció"):
        load_base_os_update(path)


def test_phase_10_6_rejects_non_trixie_suite(tmp_path: Path) -> None:
    path = _copy_policy(tmp_path, ("suite: trixie\n", "suite: forky\n", 1))
    with pytest.raises(BaseOsUpdateError, match="Debian 13/trixie"):
        load_base_os_update(path)


def test_installer_writes_root_owned_policy_and_protects_xaac_packages(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    plan = create_base_os_update_plan(rootfs, POLICY)
    outputs = BaseOsUpdateInstaller().install(plan)
    assert len(outputs) == 4
    policy = json.loads(plan.output("policy").read_text(encoding="utf-8"))
    assert policy["phase"] == "10.6"
    assert policy["outputs"]["state"] == "/var/lib/xaac-update/base-os-state.json"
    state = json.loads(plan.output("state").read_text(encoding="utf-8"))
    assert state["status"] == "idle"
    prefs = plan.output("apt_preferences").read_text(encoding="utf-8")
    assert "xaac-thinclient" in prefs and "Pin-Priority: -1" in prefs
    conf = plan.output("apt_conf").read_text(encoding="utf-8")
    assert 'AllowUnauthenticated "false"' in conf
    assert stat.S_IMODE(plan.output("checkpoint").stat().st_mode) == 0o700


def test_installer_rejects_symlink_destination(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    plan = create_base_os_update_plan(rootfs, POLICY)
    target = plan.output("policy")
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("safe", encoding="utf-8")
    target.symlink_to(outside)
    with pytest.raises(BaseOsUpdateError, match="enllaç simbòlic"):
        BaseOsUpdateInstaller().install(plan)
