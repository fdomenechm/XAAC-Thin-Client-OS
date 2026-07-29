from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xaac_thin_client_os.xaac_agent_package import (
    XaacAgentInstaller,
    XaacAgentPackageError,
    create_xaac_agent_plan,
    load_xaac_agent_profile,
)


def _artifact(root: Path) -> Path:
    path = root / "packages/xaac-agent_1.0.0_amd64.deb"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"agent-deb")
    return path


def _metadata_runner(command, **kwargs):  # type: ignore[no-untyped-def]
    return subprocess.CompletedProcess(command, 0, "xaac-agent\n1.0.0\namd64\npython3\n", "")


def test_load_agent_profile(project_root: Path) -> None:
    profile = load_xaac_agent_profile(project_root / "config/xaac-agent-package.yaml")
    assert profile["service"]["user"] == "xaac-agent"
    assert profile["security"]["shell"] == "/usr/sbin/nologin"


def test_plan_validates_agent_package(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_xaac_agent_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml", runner=_metadata_runner)
    assert plan.manifest()["service"] == "xaac-agent.service"


def test_plan_rejects_wrong_metadata(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    def wrong(command, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(command, 0, "wrong\n1.0.0\namd64\npython3\n", "")
    with pytest.raises(XaacAgentPackageError, match="metadades"):
        create_xaac_agent_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml", runner=wrong)


def test_installer_dry_run_is_side_effect_free(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_xaac_agent_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml", runner=_metadata_runner)
    assert XaacAgentInstaller().execute(plan, dry_run=True) == ()
    assert not plan.rootfs.exists()


def test_installer_writes_service_directories_and_config(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_xaac_agent_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml", runner=_metadata_runner)
    calls = []
    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(command))
        rc = 1 if command[2] in {"getent", "id"} else 0
        return subprocess.CompletedProcess(command, rc, "", "")
    written = XaacAgentInstaller().execute(plan, runner=runner)
    assert len(written) == 6
    unit = plan.rootfs / "etc/systemd/system/xaac-agent.service"
    assert "NoNewPrivileges=true" in unit.read_text()
    assert (plan.rootfs / "var/lib/xaac-agent").stat().st_mode & 0o777 == 0o750
    assert any("useradd" in command for command in calls)
    assert any(command[-2:] == ("enable", "xaac-agent.service") for command in calls)


def test_installer_is_idempotent_for_existing_account(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_xaac_agent_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml", runner=_metadata_runner)
    calls = []
    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")
    XaacAgentInstaller().execute(plan, runner=runner)
    assert not any("groupadd" in command or "useradd" in command for command in calls)


def test_installer_rejects_symlink(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_xaac_agent_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml", runner=_metadata_runner)
    target = plan.rootfs / "etc/systemd/system/xaac-agent.service"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(XaacAgentPackageError, match="enllaç simbòlic"):
        XaacAgentInstaller().execute(plan, runner=_metadata_runner)


def test_cli_exposes_agent_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["install-xaac-agent", "--dry-run"])
    assert args.command == "install-xaac-agent"
