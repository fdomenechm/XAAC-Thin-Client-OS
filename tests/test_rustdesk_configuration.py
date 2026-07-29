from __future__ import annotations
import json
from pathlib import Path
import pytest
from xaac_thin_client_os.rustdesk_configuration import (
    RustDeskConfigurationError, RustDeskConfigurationManager,
    create_rustdesk_configuration_plan, load_rustdesk_configuration,
)


def test_profile_defines_managed_servers_and_policies(project_root: Path) -> None:
    profile = load_rustdesk_configuration(project_root / "config/rustdesk-central.yaml")
    assert profile["servers"]["id"].endswith(":21116")
    assert profile["policies"]["managed"] is True
    assert profile["update"]["managed_by_xaac"] is True


def test_plan_payload_excludes_output_paths(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_configuration_plan(tmp_path / "rootfs", project_root / "config/rustdesk-central.yaml")
    assert "outputs" not in plan.payload()
    assert plan.payload()["revision"] == 1


def test_apply_writes_active_configuration_with_restricted_mode(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_configuration_plan(tmp_path / "rootfs", project_root / "config/rustdesk-central.yaml")
    written = RustDeskConfigurationManager().apply(plan)
    assert written == (plan.target("active"),)
    assert json.loads(plan.target("active").read_text())["servers"]["relay"].endswith(":21117")
    assert plan.target("active").stat().st_mode & 0o777 == 0o640


def test_second_apply_creates_backup(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_configuration_plan(tmp_path / "rootfs", project_root / "config/rustdesk-central.yaml")
    manager = RustDeskConfigurationManager(); manager.apply(plan)
    first = plan.target("active").read_bytes(); manager.apply(plan)
    assert plan.target("backup").read_bytes() == first


def test_rollback_restores_previous_configuration(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_configuration_plan(tmp_path / "rootfs", project_root / "config/rustdesk-central.yaml")
    manager = RustDeskConfigurationManager(); manager.apply(plan)
    original = json.loads(plan.target("active").read_text()); original["revision"] = 99
    plan.target("active").write_text(json.dumps(original)); manager.apply(plan)
    manager.rollback(plan)
    assert json.loads(plan.target("active").read_text())["revision"] == 99


def test_dry_run_does_not_create_rootfs(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_configuration_plan(tmp_path / "rootfs", project_root / "config/rustdesk-central.yaml")
    assert RustDeskConfigurationManager().apply(plan, dry_run=True) == ()
    assert not plan.rootfs.exists()


def test_rejects_insecure_api(project_root: Path, tmp_path: Path) -> None:
    text = (project_root / "config/rustdesk-central.yaml").read_text().replace("https://support", "http://support")
    bad = tmp_path / "bad.yaml"; bad.write_text(text)
    with pytest.raises(RustDeskConfigurationError, match="API RustDesk insegura"):
        load_rustdesk_configuration(bad)


def test_rejects_symlink_active_target(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_configuration_plan(tmp_path / "rootfs", project_root / "config/rustdesk-central.yaml")
    target = plan.target("active"); target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "outside")
    with pytest.raises(RustDeskConfigurationError, match="enllaç simbòlic"):
        RustDeskConfigurationManager().apply(plan)


def test_cli_exposes_central_configuration_commands() -> None:
    from xaac_thin_client_os.cli import build_parser
    assert build_parser().parse_args(["configure-rustdesk-central", "--dry-run"]).command == "configure-rustdesk-central"
    assert build_parser().parse_args(["rollback-rustdesk-central"]).command == "rollback-rustdesk-central"
