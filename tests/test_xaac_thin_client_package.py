from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from xaac_thin_client_os.xaac_thin_client_package import (
    DebianPackageMetadata,
    XaacThinClientPackageError,
    XaacThinClientPackageInstaller,
    create_xaac_thin_client_package_plan,
    inspect_debian_package,
    load_xaac_thin_client_package_profile,
    validate_package_metadata,
)


def _artifact(project_root: Path) -> Path:
    path = project_root / "packages/xaac-thinclient_1.0.0_all.deb"
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        path.write_bytes(b"fake-deb-for-tests")
    return path


def _runner(command, **kwargs):  # type: ignore[no-untyped-def]
    return subprocess.CompletedProcess(command, 0, "xaac-thinclient\n1.0.0\nall\npython3, python3-gi, gir1.2-gtk-4.0\n", "")


def test_load_profile(project_root: Path) -> None:
    profile = load_xaac_thin_client_package_profile(project_root / "config/xaac-thin-client-package.yaml")
    assert profile["package"]["name"] == "xaac-thinclient"
    assert profile["update"]["verify_before_install"] is True


def test_inspect_package_uses_dpkg_deb(project_root: Path) -> None:
    artifact = _artifact(project_root)
    metadata = inspect_debian_package(artifact, runner=_runner)
    assert metadata.package == "xaac-thinclient"
    assert metadata.sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()


def test_plan_validates_and_is_auditable(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_xaac_thin_client_package_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-thin-client-package.yaml", runner=_runner)
    assert plan.to_manifest()["version"] == "1.0.0"
    assert plan.install_commands()[0][-2:] == ("--install", "/var/cache/xaac/packages/xaac-thinclient.deb")


def test_validation_accepts_newer_patch(project_root: Path) -> None:
    profile = load_xaac_thin_client_package_profile(project_root / "config/xaac-thin-client-package.yaml")
    validate_package_metadata(DebianPackageMetadata("xaac-thinclient", "1.0.2", "all", ("gir1.2-gtk-4.0", "python3", "python3-gi"), "0" * 64), profile)


def test_validation_rejects_wrong_architecture(project_root: Path) -> None:
    profile = load_xaac_thin_client_package_profile(project_root / "config/xaac-thin-client-package.yaml")
    with pytest.raises(XaacThinClientPackageError, match="arquitectura"):
        validate_package_metadata(DebianPackageMetadata("xaac-thinclient", "1.0.0", "arm64", ("gir1.2-gtk-4.0", "python3", "python3-gi"), "0" * 64), profile)


def test_validation_rejects_missing_dependency(project_root: Path) -> None:
    profile = load_xaac_thin_client_package_profile(project_root / "config/xaac-thin-client-package.yaml")
    with pytest.raises(XaacThinClientPackageError, match="dependències"):
        validate_package_metadata(DebianPackageMetadata("xaac-thinclient", "1.0.0", "all", ("python3",), "0" * 64), profile)


def test_plan_rejects_missing_artifact(project_root: Path, tmp_path: Path) -> None:
    temp_project = tmp_path / "project"
    (temp_project / "config").mkdir(parents=True)
    (temp_project / "config/xaac-thin-client-package.yaml").write_text(
        (project_root / "config/xaac-thin-client-package.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(XaacThinClientPackageError, match="No existeix"):
        create_xaac_thin_client_package_plan(tmp_path / "rootfs", temp_project, temp_project / "config/xaac-thin-client-package.yaml", runner=_runner)


def test_installer_dry_run_writes_nothing(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_xaac_thin_client_package_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-thin-client-package.yaml", runner=_runner)
    assert XaacThinClientPackageInstaller().execute(plan, dry_run=True) == ()
    assert not plan.rootfs.exists()


def test_installer_copies_configures_and_runs_commands(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_xaac_thin_client_package_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-thin-client-package.yaml", runner=_runner)
    calls = []
    def install_runner(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")
    written = XaacThinClientPackageInstaller().execute(plan, runner=install_runner)
    assert len(written) == 3
    assert written[0].read_bytes() == _artifact(project_root).read_bytes()
    assert len(calls) == 2


def test_installer_rejects_symlink(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_xaac_thin_client_package_plan(tmp_path / "rootfs", project_root, project_root / "config/xaac-thin-client-package.yaml", runner=_runner)
    target = plan.rootfs / "var/cache/xaac/packages/xaac-thinclient.deb"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(XaacThinClientPackageError, match="enllaç simbòlic"):
        XaacThinClientPackageInstaller().execute(plan, runner=_runner)


def test_cli_parser_exposes_install_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["install-xaac-thin-client", "--dry-run"])
    assert args.command == "install-xaac-thin-client"
    assert args.dry_run is True


def test_real_debian_package_matches_profile(project_root: Path) -> None:
    artifact = project_root / "packages/xaac-thinclient_1.0.0_all.deb"
    metadata = inspect_debian_package(artifact)
    profile = load_xaac_thin_client_package_profile(project_root / "config/xaac-thin-client-package.yaml")
    validate_package_metadata(metadata, profile)
    assert metadata.package == "xaac-thinclient"
    assert metadata.version == "1.0.0"
    assert metadata.architecture == "all"
