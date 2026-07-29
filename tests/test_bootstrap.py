from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xaac_thin_client_os.bootstrap import (
    BootstrapError,
    BootstrapPlan,
    BootstrapRunner,
    create_bootstrap_plan,
    find_debootstrap,
)
from xaac_thin_client_os.configuration import load_project_configuration


def _plan(tmp_path: Path) -> BootstrapPlan:
    return BootstrapPlan(
        executable=Path("/usr/sbin/debootstrap"),
        suite="trixie",
        target=tmp_path / "run" / "rootfs",
        mirror="https://deb.debian.org/debian",
        architecture="amd64",
        components=("main", "non-free-firmware"),
    )


def test_find_debootstrap_returns_absolute_path() -> None:
    assert find_debootstrap(search=lambda _: "/usr/sbin/debootstrap") == Path(
        "/usr/sbin/debootstrap"
    )


def test_find_debootstrap_rejects_missing_tool() -> None:
    with pytest.raises(BootstrapError, match="apt install debootstrap"):
        find_debootstrap(search=lambda _: None)


def test_find_debootstrap_rejects_relative_path() -> None:
    with pytest.raises(BootstrapError, match="absoluta"):
        find_debootstrap(search=lambda _: "debootstrap")


def test_plan_builds_expected_command(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert plan.command() == (
        "/usr/sbin/debootstrap",
        "--arch=amd64",
        "--variant=minbase",
        "--components=main,non-free-firmware",
        "trixie",
        str(tmp_path / "run" / "rootfs"),
        "https://deb.debian.org/debian",
    )


def test_plan_manifest_is_json_compatible(tmp_path: Path) -> None:
    payload = _plan(tmp_path).to_manifest()
    assert payload["suite"] == "trixie"
    assert payload["components"] == ["main", "non-free-firmware"]
    assert payload["command"][1] == "--arch=amd64"  # type: ignore[index]


def test_create_plan_uses_project_configuration(project_root: Path, tmp_path: Path) -> None:
    configuration = load_project_configuration(project_root)
    plan = create_bootstrap_plan(
        configuration.build,
        tmp_path / "workspace" / "rootfs",
        executable=Path("/usr/sbin/debootstrap"),
    )
    assert plan.suite == "trixie"
    assert plan.architecture == "amd64"
    assert plan.variant == "minbase"


def test_create_plan_rejects_non_empty_target(project_root: Path, tmp_path: Path) -> None:
    target = tmp_path / "workspace" / "rootfs"
    target.mkdir(parents=True)
    (target / "existing").write_text("x", encoding="utf-8")
    configuration = load_project_configuration(project_root)
    with pytest.raises(BootstrapError, match="no està buida"):
        create_bootstrap_plan(
            configuration.build,
            target,
            executable=Path("/usr/sbin/debootstrap"),
        )


def test_create_plan_rejects_top_level_target(project_root: Path) -> None:
    configuration = load_project_configuration(project_root)
    with pytest.raises(BootstrapError, match="insegura"):
        create_bootstrap_plan(
            configuration.build,
            Path("/rootfs"),
            executable=Path("/usr/sbin/debootstrap"),
        )


def test_dry_run_writes_log_without_privileges(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    log = tmp_path / "logs" / "debootstrap.log"
    runner = BootstrapRunner(geteuid=lambda: 1000)
    result = runner.execute(plan, log, dry_run=True)
    assert not result.executed
    assert "DRY-RUN" in log.read_text(encoding="utf-8")
    assert not plan.target.exists()


def test_execution_requires_root(tmp_path: Path) -> None:
    runner = BootstrapRunner(geteuid=lambda: 1000)
    with pytest.raises(BootstrapError, match="root"):
        runner.execute(_plan(tmp_path), tmp_path / "bootstrap.log")


def test_successful_execution_validates_debian_marker(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == list(plan.command())
        (plan.target / "etc").mkdir(parents=True)
        (plan.target / "etc" / "debian_version").write_text("13.0\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    log = tmp_path / "logs" / "debootstrap.log"
    result = BootstrapRunner(run=run, geteuid=lambda: 0).execute(plan, log)
    assert result.executed
    assert "RETURN_CODE: 0" in log.read_text(encoding="utf-8")


def test_failed_execution_removes_partial_rootfs(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        (plan.target / "partial").mkdir(parents=True)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failure")

    with pytest.raises(BootstrapError, match="codi 1"):
        BootstrapRunner(run=run, geteuid=lambda: 0).execute(
            plan, tmp_path / "logs" / "debootstrap.log"
        )
    assert not plan.target.exists()


def test_failed_execution_can_keep_partial_rootfs(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        plan.target.mkdir(parents=True)
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="failure")

    with pytest.raises(BootstrapError):
        BootstrapRunner(run=run, geteuid=lambda: 0).execute(
            plan,
            tmp_path / "logs" / "debootstrap.log",
            keep_partial=True,
        )
    assert plan.target.exists()


def test_missing_debian_marker_is_failure(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        plan.target.mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    with pytest.raises(BootstrapError, match="debian_version"):
        BootstrapRunner(run=run, geteuid=lambda: 0).execute(
            plan, tmp_path / "logs" / "debootstrap.log"
        )
    assert not plan.target.exists()
