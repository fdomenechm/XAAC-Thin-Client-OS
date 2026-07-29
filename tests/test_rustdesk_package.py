from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xaac_thin_client_os.rustdesk_package import (
    RustDeskDebMetadata, RustDeskPackageError, RustDeskPackageManager,
    create_rustdesk_package_plan, load_rustdesk_package_profile,
    validate_rustdesk_metadata,
)


def _artifact(root: Path) -> Path:
    path = root / "packages/rustdesk-xaac_1.0.0_amd64.deb"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"rustdesk-xaac-test-deb")
    return path


def _runner(command, **kwargs):  # type: ignore[no-untyped-def]
    return subprocess.CompletedProcess(command, 0, "rustdesk-xaac\n1.0.0\namd64\nlibgtk-3-0, libxdo3, libxcb-randr0\n", "")


def test_load_profile_declares_controlled_origin(project_root: Path) -> None:
    profile = load_rustdesk_package_profile(project_root / "config/rustdesk-package.yaml")
    assert profile["origin"]["vendor"] == "XAAC"
    assert profile["package"]["name"] == "rustdesk-xaac"


def test_plan_validates_version_dependencies_and_origin(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_rustdesk_package_plan(tmp_path / "rootfs", project_root, project_root / "config/rustdesk-package.yaml", runner=_runner)
    assert plan.manifest()["version"] == "1.0.0"
    assert plan.install_commands()[0][-1] == "/var/cache/xaac/packages/rustdesk-xaac.deb"
    assert plan.uninstall_commands()[0][-1] == "rustdesk-xaac"


def test_rejects_wrong_package_metadata(project_root: Path) -> None:
    profile = load_rustdesk_package_profile(project_root / "config/rustdesk-package.yaml")
    with pytest.raises(RustDeskPackageError, match="metadades"):
        validate_rustdesk_metadata(RustDeskDebMetadata("rustdesk", "1.0.0", "amd64", tuple(profile["package"]["dependencies"]), "0" * 64), profile)


def test_rejects_missing_dependency(project_root: Path) -> None:
    profile = load_rustdesk_package_profile(project_root / "config/rustdesk-package.yaml")
    with pytest.raises(RustDeskPackageError, match="dependències"):
        validate_rustdesk_metadata(RustDeskDebMetadata("rustdesk-xaac", "1.0.0", "amd64", ("libgtk-3-0",), "0" * 64), profile)


def test_install_is_dry_run_safe(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_rustdesk_package_plan(tmp_path / "rootfs", project_root, project_root / "config/rustdesk-package.yaml", runner=_runner)
    assert RustDeskPackageManager().install(plan, dry_run=True) == ()
    assert not plan.rootfs.exists()


def test_install_and_uninstall_are_complete(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_rustdesk_package_plan(tmp_path / "rootfs", project_root, project_root / "config/rustdesk-package.yaml", runner=_runner)
    calls = []
    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(command)); return subprocess.CompletedProcess(command, 0, "", "")
    written = RustDeskPackageManager().install(plan, runner=runner)
    assert len(written) == 2 and all(path.exists() for path in written)
    removed = RustDeskPackageManager().uninstall(plan, runner=runner)
    assert len(removed) == 2 and all(not path.exists() for path in removed)
    assert any("purge" in command for command in calls)


def test_install_rejects_symlink(project_root: Path, tmp_path: Path) -> None:
    _artifact(project_root)
    plan = create_rustdesk_package_plan(tmp_path / "rootfs", project_root, project_root / "config/rustdesk-package.yaml", runner=_runner)
    target = plan.rootfs / "etc/xaac/rustdesk/package.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(RustDeskPackageError, match="enllaç simbòlic"):
        RustDeskPackageManager().install(plan, runner=_runner)


def test_cli_exposes_rustdesk_commands() -> None:
    from xaac_thin_client_os.cli import build_parser
    assert build_parser().parse_args(["install-rustdesk", "--dry-run"]).command == "install-rustdesk"
    assert build_parser().parse_args(["uninstall-rustdesk", "--dry-run"]).command == "uninstall-rustdesk"
