from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xaac_thin_client_os.xaac_agent_package import (
    XaacAgentInstaller,
    XaacAgentPackageError,
    create_xaac_agent_plan,
    inspect_agent_package,
    load_xaac_agent_profile,
)


def _artifact(project_root: Path) -> Path:
    return project_root / "packages/xaac-agent_1.0.0-5_amd64.deb"


def _metadata_runner(command, **kwargs):  # type: ignore[no-untyped-def]
    return subprocess.CompletedProcess(
        command,
        0,
        "xaac-agent\n1.0.0-5\namd64\nlibc6, ca-certificates, systemd, openssl\n",
        "",
    )


def test_load_agent_profile_declares_debian_owned_resources(project_root: Path) -> None:
    profile = load_xaac_agent_profile(project_root / "config/xaac-agent-package.yaml")
    assert profile["schema_version"] == 3
    assert profile["package"]["application_version"] == "1.0.0"
    assert profile["package"]["version"] == "1.0.0-5"
    assert profile["ownership"]["configuration_root"] == "/etc/xaac-agent"
    assert profile["ownership"]["runtime_root"] == "/opt/xaac-agent/runtime"
    assert profile["ownership"]["command_group"] == "xaac-command"
    assert profile["ownership"]["ipc_group"] == "xaac-ipc"
    assert profile["ownership"]["runtime_directory"] == "/run/xaac-agent/runtime"
    assert "/opt/xaac-agent/runtime/bin/xaac-agent-admin" in profile["installation"]["required_paths"]
    assert "/usr/sbin/xaac-agent-admin" in profile["installation"]["required_paths"]


def test_real_agent_artifact_matches_profile(project_root: Path, tmp_path: Path) -> None:
    plan = create_xaac_agent_plan(
        tmp_path / "rootfs",
        project_root,
        project_root / "config/xaac-agent-package.yaml",
    )
    assert plan.metadata.package == "xaac-agent"
    assert plan.metadata.version == "1.0.0-5"
    assert plan.metadata.size > 1024
    assert plan.manifest()["managed_by"] == "xaac-agent.deb"


def test_inspection_rejects_placeholder(tmp_path: Path) -> None:
    artifact = tmp_path / "xaac-agent.deb"
    artifact.write_bytes(b"agent-deb")
    with pytest.raises(XaacAgentPackageError, match="placeholder"):
        inspect_agent_package(artifact, runner=_metadata_runner)


def test_plan_rejects_wrong_metadata(project_root: Path, tmp_path: Path) -> None:
    def wrong(command, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(command, 0, "wrong\n1.0.0-5\namd64\nca-certificates, systemd, openssl\n", "")

    with pytest.raises(XaacAgentPackageError, match="metadades"):
        create_xaac_agent_plan(
            tmp_path / "rootfs",
            project_root,
            project_root / "config/xaac-agent-package.yaml",
            runner=wrong,
        )


def test_verification_requires_secure_admin_enrollment_contract(project_root: Path, tmp_path: Path) -> None:
    plan = create_xaac_agent_plan(
        tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml"
    )
    command = " ".join(plan.verification_command())
    assert "test -x /usr/sbin/xaac-agent-admin" in command
    assert "readlink /usr/sbin/xaac-agent-admin" in command
    assert "xaac-enrollment-token:-/etc/xaac-agent/enrollment.token" in command


def test_installer_dry_run_is_side_effect_free(project_root: Path, tmp_path: Path) -> None:
    plan = create_xaac_agent_plan(
        tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml"
    )
    assert XaacAgentInstaller().execute(plan, dry_run=True) == ()
    assert not plan.rootfs.exists()


def test_installer_delegates_installation_to_deb(project_root: Path, tmp_path: Path) -> None:
    plan = create_xaac_agent_plan(
        tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml"
    )
    calls: list[tuple[str, ...]] = []

    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    written = XaacAgentInstaller().execute(plan, runner=runner)
    assert len(written) == 2
    assert calls[0] == plan.install_command()
    assert calls[1] == plan.verification_command()
    assert not (plan.rootfs / "etc/systemd/system/xaac-agent.service").exists()
    assert not (plan.rootfs / "etc/xaac/agent/agent.yaml").exists()
    manifest = plan.rootfs / "etc/xaac/packages/xaac-agent.json"
    assert manifest.is_file()
    assert "1.0.0-5" in manifest.read_text(encoding="utf-8")


def test_installer_rejects_symlink_manifest(project_root: Path, tmp_path: Path) -> None:
    plan = create_xaac_agent_plan(
        tmp_path / "rootfs", project_root, project_root / "config/xaac-agent-package.yaml"
    )
    target = plan.rootfs / "etc/xaac/packages/xaac-agent.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(XaacAgentPackageError, match="enllaç simbòlic"):
        XaacAgentInstaller().execute(plan, runner=_metadata_runner)


def test_cli_exposes_agent_command() -> None:
    from xaac_thin_client_os.cli import build_parser

    args = build_parser().parse_args(["install-xaac-agent", "--dry-run"])
    assert args.command == "install-xaac-agent"
