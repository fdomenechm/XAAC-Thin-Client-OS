import json
from pathlib import Path

import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.installer_builder import (
    InstallerBuilder,
    InstallerBuilderError,
    create_installer_build_plan,
    load_installer_builder,
)

ROOT = Path(__file__).parents[1]


def copied(tmp_path, old, new):
    path = tmp_path / "installer-builder.yaml"
    path.write_text((ROOT / "config/installer-builder.yaml").read_text().replace(old, new))
    return path


def test_loads_installer_policy():
    profile = load_installer_builder(ROOT / "config/installer-builder.yaml")
    assert profile["safety"]["explicit_disk_selection"] is True
    assert profile["bootloader"]["type"] == "grub-efi-amd64"


def test_manifest_is_stable():
    manifest = create_installer_build_plan(ROOT, ROOT / "config/installer-builder.yaml").manifest()
    assert manifest["steps"] == ["select-disk", "confirm", "partition", "copy", "bootloader", "verify", "summary"]
    assert manifest["minimum_disk_mib"] == 7168


def test_prepares_installer_assets(tmp_path):
    project = tmp_path / "project"; project.mkdir()
    cfg = project / "installer.yaml"; cfg.write_text((ROOT / "config/installer-builder.yaml").read_text())
    plan = create_installer_build_plan(project, cfg)
    assert len(InstallerBuilder().prepare(plan)) == 4
    config = json.loads(plan.output("installer_config").read_text())
    assert [part["label"] for part in config["partitions"]] == ["XAAC_EFI", "XAAC_ROOT", "XAAC_DATA", "XAAC_RECOVERY"]
    script = plan.output("installer_script").read_text()
    assert "INSTALL XAAC" in script and "grub-install --target=x86_64-efi" in script
    assert 'KERNEL_VERSION=$(find "$WORK/root/lib/modules"' in script
    assert 'install -m 0644 "$SOURCE_DIR/vmlinuz"' in script
    assert 'grub.cfg has no bootable Linux menuentry' in script
    assert "sha256sum -c" in script and "findmnt" in script
    assert "xaac-admin password" in script
    assert "stty -echo" in script
    assert '${#ADMIN_PASSWORD}' in script
    assert 'openssl passwd -6 -stdin' in script
    assert 'pamtester login xaac-admin authenticate' in script
    assert 'passwd -S xaac-admin' in script
    assert "usermod --password" in script
    assert "chage -E -1 -I -1 -m 0 xaac-admin" in script
    assert "getent shadow xaac-admin" in script
    assert '/var/lib/xaac/admin/password-changed' in script
    assert 'unset ADMIN_PASSWORD' in script
    assert plan.output("installer_script").stat().st_mode & 0o777 == 0o750


def test_summary_schema_requires_final_status(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/installer-builder.yaml").read_text())
    plan = create_installer_build_plan(project, cfg); InstallerBuilder().prepare(plan)
    schema = json.loads(plan.output("summary_schema").read_text())
    assert schema["required"] == ["status", "target_disk", "partitions", "bootloader", "verification"]
    assert schema["additionalProperties"] is False


def test_idempotent(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/installer-builder.yaml").read_text())
    plan = create_installer_build_plan(project, cfg); builder = InstallerBuilder(); builder.prepare(plan)
    before = [plan.output("manifest").read_bytes(), plan.output("installer_script").read_bytes()]
    builder.prepare(plan)
    assert before == [plan.output("manifest").read_bytes(), plan.output("installer_script").read_bytes()]


def test_dry_run(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/installer-builder.yaml").read_text())
    paths = InstallerBuilder().prepare(create_installer_build_plan(project, cfg), dry_run=True)
    assert len(paths) == 4 and not any(path.exists() for path in paths)


def test_rejects_missing_confirmation(tmp_path):
    with pytest.raises(InstallerBuilderError, match="seguretat"):
        load_installer_builder(copied(tmp_path, "exact_confirmation_phrase: true", "exact_confirmation_phrase: false"))


def test_rejects_wrong_phrase(tmp_path):
    with pytest.raises(InstallerBuilderError, match="Frase"):
        load_installer_builder(copied(tmp_path, "confirmation_phrase: INSTALL XAAC", "confirmation_phrase: YES"))


def test_rejects_incomplete_partitions(tmp_path):
    with pytest.raises(InstallerBuilderError, match="Particions"):
        load_installer_builder(copied(tmp_path, "label: XAAC_RECOVERY", "label: RECOVERY"))


def test_rejects_checksum_disabled(tmp_path):
    with pytest.raises(InstallerBuilderError, match="SHA-256"):
        load_installer_builder(copied(tmp_path, "verify_sha256: true", "verify_sha256: false"))


def test_rejects_symlink(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/installer-builder.yaml").read_text())
    target = project / ".build/installer/manifest.json"; target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "outside")
    with pytest.raises(InstallerBuilderError, match="enllaç"):
        InstallerBuilder().prepare(create_installer_build_plan(project, cfg))


def test_cli(tmp_path):
    assert build_parser().parse_args(["build-installer", "--dry-run"]).command == "build-installer"
    (tmp_path / "config").mkdir(); (tmp_path / "config/installer-builder.yaml").write_text((ROOT / "config/installer-builder.yaml").read_text())
    assert main(["--root", str(tmp_path), "build-installer", "--dry-run"]) == 0


def test_installer_verifies_admin_password_with_pam(project_root: Path, tmp_path: Path) -> None:
    profile = project_root / "config/installer-builder.yaml"
    plan = create_installer_build_plan(tmp_path, profile)
    InstallerBuilder().prepare(plan)
    script = plan.output("installer_script").read_text(encoding="utf-8")
    assert "openssl passwd -6 -stdin" in script
    assert "usermod --password" in script
    assert "pamtester login xaac-admin authenticate" in script
    assert "chpasswd" not in script
