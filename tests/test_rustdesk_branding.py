from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaac_thin_client_os.rustdesk_branding import (
    RustDeskBrandingError,
    RustDeskBrandingInstaller,
    create_rustdesk_branding_plan,
    load_rustdesk_branding_profile,
)


def test_profile_defines_complete_xaac_identity(project_root: Path) -> None:
    profile = load_rustdesk_branding_profile(project_root / "config/rustdesk-branding.yaml")
    assert profile["identity"]["product_name"] == "XAAC Remote Support"
    assert profile["servers"]["configuration_managed"] is True
    assert profile["version"]["upstream_product"] == "RustDesk"


def test_plan_exposes_branding_manifest(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_branding_plan(
        tmp_path / "rootfs", project_root, project_root / "config/rustdesk-branding.yaml"
    )
    manifest = plan.manifest()
    assert manifest["identity"]["icon_name"] == "xaac-remote-support"
    assert manifest["version"]["product_version"] == "1.0.0"
    assert len(plan.target_paths()) == 5


def test_install_writes_assets_desktop_manifest_and_environment(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_branding_plan(
        tmp_path / "rootfs", project_root, project_root / "config/rustdesk-branding.yaml"
    )
    written = RustDeskBrandingInstaller().install(plan)
    assert len(written) == 5
    assert all(path.is_file() for path in written)
    manifest = json.loads((plan.rootfs / "etc/xaac/rustdesk/branding.json").read_text())
    assert manifest["texts"]["window_title"] == "XAAC Remote Support"
    desktop = (plan.rootfs / "usr/share/applications/xaac-remote-support.desktop").read_text()
    assert "Name=XAAC Remote Support" in desktop
    assert "Icon=xaac-remote-support" in desktop


def test_install_is_idempotent(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_branding_plan(
        tmp_path / "rootfs", project_root, project_root / "config/rustdesk-branding.yaml"
    )
    installer = RustDeskBrandingInstaller()
    first = installer.install(plan)
    before = {path: path.read_bytes() for path in first}
    second = installer.install(plan)
    assert first == second
    assert before == {path: path.read_bytes() for path in second}


def test_dry_run_does_not_create_rootfs(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_branding_plan(
        tmp_path / "rootfs", project_root, project_root / "config/rustdesk-branding.yaml"
    )
    assert RustDeskBrandingInstaller().install(plan, dry_run=True) == ()
    assert not plan.rootfs.exists()


def test_rejects_unsafe_asset_path(project_root: Path, tmp_path: Path) -> None:
    profile = (project_root / "config/rustdesk-branding.yaml").read_text()
    bad = tmp_path / "branding.yaml"
    bad.write_text(profile.replace("assets/rustdesk/xaac-remote-support.svg", "../outside.svg"))
    with pytest.raises(RustDeskBrandingError, match="insegur"):
        load_rustdesk_branding_profile(bad)


def test_rejects_symlink_target(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_branding_plan(
        tmp_path / "rootfs", project_root, project_root / "config/rustdesk-branding.yaml"
    )
    target = plan.rootfs / "etc/xaac/rustdesk/branding.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(RustDeskBrandingError, match="enllaç simbòlic"):
        RustDeskBrandingInstaller().install(plan)


def test_cli_exposes_branding_command() -> None:
    from xaac_thin_client_os.cli import build_parser

    args = build_parser().parse_args(["configure-rustdesk-branding", "--dry-run"])
    assert args.command == "configure-rustdesk-branding"
    assert args.dry_run is True
