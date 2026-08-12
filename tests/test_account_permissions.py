from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.account_permissions import (
    AccountPermissionsError,
    AccountPermissionsInstaller,
    create_account_permissions_plan,
    load_account_permissions,
)
from xaac_thin_client_os.cli import build_parser


def test_profile_defines_required_accounts(project_root: Path) -> None:
    profile = load_account_permissions(project_root / "config/account-permissions.yaml")
    assert {item["name"] for item in profile["accounts"]} == {"root", "xaac-admin", "xaac-kiosk", "xaac-agent", "xaac-rustdesk"}
    assert all(item["locked"] for item in profile["accounts"])


def test_noninteractive_accounts_use_nologin(project_root: Path) -> None:
    profile = load_account_permissions(project_root / "config/account-permissions.yaml")
    accounts = {item["name"]: item for item in profile["accounts"]}
    assert accounts["xaac-kiosk"]["shell"] == "/usr/sbin/nologin"
    assert accounts["xaac-agent"]["interactive_login"] == "denied"
    assert accounts["xaac-rustdesk"]["interactive_login"] == "denied"


def test_plan_rejects_unsafe_root(project_root: Path) -> None:
    with pytest.raises(AccountPermissionsError, match="Rootfs insegur"):
        create_account_permissions_plan(Path("/"), project_root / "config/account-permissions.yaml")


def test_dry_run_does_not_write(project_root: Path, tmp_path: Path) -> None:
    plan = create_account_permissions_plan(tmp_path / "rootfs", project_root / "config/account-permissions.yaml")
    paths = AccountPermissionsInstaller().install(plan, dry_run=True)
    assert len(paths) == 4
    assert not any(path.exists() for path in paths)


def test_install_writes_policy_and_state(project_root: Path, tmp_path: Path) -> None:
    plan = create_account_permissions_plan(tmp_path / "rootfs", project_root / "config/account-permissions.yaml")
    paths = AccountPermissionsInstaller().install(plan)
    policy = json.loads(plan.destination("policy").read_text(encoding="utf-8"))
    state = json.loads(plan.destination("state").read_text(encoding="utf-8"))
    assert len(paths) == 4
    assert policy["policy_id"] == "xaac-account-permissions-v1"
    assert state["least_privilege"] is True
    assert "u xaac-agent" in plan.destination("sysusers").read_text(encoding="utf-8")


def test_install_is_idempotent(project_root: Path, tmp_path: Path) -> None:
    plan = create_account_permissions_plan(tmp_path / "rootfs", project_root / "config/account-permissions.yaml")
    installer = AccountPermissionsInstaller()
    installer.install(plan)
    before = {key: plan.destination(key).read_bytes() for key in plan.profile["outputs"]}
    installer.install(plan)
    assert before == {key: plan.destination(key).read_bytes() for key in plan.profile["outputs"]}


def test_freerdp_certificate_store_is_created_for_kiosk(project_root: Path, tmp_path: Path) -> None:
    plan = create_account_permissions_plan(tmp_path / "rootfs", project_root / "config/account-permissions.yaml")
    AccountPermissionsInstaller().install(plan)
    tmpfiles = plan.destination("tmpfiles").read_text(encoding="utf-8")
    assert "d /etc/xaac/freerdp 700 xaac-kiosk xaac-kiosk -" in tmpfiles
    assert "d /etc/xaac/freerdp/server 700 xaac-kiosk xaac-kiosk -" in tmpfiles
    assert "Z /etc/xaac/freerdp/server 700 xaac-kiosk xaac-kiosk -" in tmpfiles


def test_installed_permissions_are_restrictive(project_root: Path, tmp_path: Path) -> None:
    plan = create_account_permissions_plan(tmp_path / "rootfs", project_root / "config/account-permissions.yaml")
    AccountPermissionsInstaller().install(plan)
    assert plan.destination("policy").stat().st_mode & 0o777 == 0o640
    assert plan.destination("state").stat().st_mode & 0o777 == 0o640
    assert plan.destination("sysusers").stat().st_mode & 0o777 == 0o644


def test_symlink_destination_is_rejected(project_root: Path, tmp_path: Path) -> None:
    plan = create_account_permissions_plan(tmp_path / "rootfs", project_root / "config/account-permissions.yaml")
    target = plan.destination("policy")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(AccountPermissionsError, match="enllaç simbòlic"):
        AccountPermissionsInstaller().install(plan)


def test_unknown_primary_group_is_rejected(project_root: Path, tmp_path: Path) -> None:
    data = yaml.safe_load((project_root / "config/account-permissions.yaml").read_text(encoding="utf-8"))
    data["accounts"][1]["primary_group"] = "missing"
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(AccountPermissionsError, match="Grup principal desconegut"):
        load_account_permissions(path)


def test_interactive_service_shell_is_rejected(project_root: Path, tmp_path: Path) -> None:
    data = yaml.safe_load((project_root / "config/account-permissions.yaml").read_text(encoding="utf-8"))
    data["accounts"][3]["shell"] = "/bin/bash"
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(AccountPermissionsError, match="shell insegura"):
        load_account_permissions(path)


def test_cli_exposes_account_permissions_command() -> None:
    args = build_parser().parse_args(["configure-account-permissions", "--dry-run"])
    assert args.command == "configure-account-permissions"
    assert args.dry_run is True
