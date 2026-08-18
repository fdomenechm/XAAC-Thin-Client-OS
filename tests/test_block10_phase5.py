from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from xaac_thin_client_os.production_builder import BuildPaths, CommandRunner, ProductionIsoBuilder

ROOT = Path(__file__).parents[1]


def _minimal_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='xaac-test'\nversion='0'\n", encoding="utf-8")
    return root


def test_phase_10_5_release_gate_is_the_production_entrypoint() -> None:
    build = (ROOT / "scripts/build-production-iso.sh").read_text(encoding="utf-8")
    gate = (ROOT / "scripts/validate-block10-release.sh").read_text(encoding="utf-8")
    assert '"$PROJECT_ROOT/scripts/validate-block10-release.sh"' in build
    assert '"$PROJECT_ROOT/scripts/validate-block9-release.sh"' not in build
    for phase in range(1, 6):
        assert f"validate-block10-phase{phase}.sh" in gate
    assert '"$PYTHON" -m pytest -q' in gate
    assert "dpkg-deb --info" in gate


def test_phase_10_5_shell_gates_are_posix_compatible() -> None:
    for name in ("validate-block10-phase5.sh", "validate-block10-release.sh"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh\n")
        assert "pipefail" not in text
        assert "BASH_SOURCE" not in text


def test_target_validator_composes_block9_and_lifecycle_checks_without_destructive_actions() -> None:
    text = (ROOT / "assets/runtime/xaac-block10-validate").read_text(encoding="utf-8")
    for expected in (
        "/usr/local/sbin/xaac-block9-validate",
        "xaac-update-admin --json status",
        "xaac-maintenance health",
        "xaac-recovery status",
        "update recovery before kiosk",
        "recovery GRUB generated",
        "factory reset disabled",
        "physical update observed",
        "physical rollback observed",
    ):
        assert expected in text
    for forbidden in (
        "xaac-update-admin update",
        "xaac-update-admin rollback",
        "xaac-recovery rollback --yes",
        "xaac-recovery repair --yes",
        "xaac-recovery network-on --yes",
        "systemctl start",
        "systemctl enable",
        "dpkg --configure",
        "update-initramfs",
        "update-grub",
    ):
        assert forbidden not in text


def test_production_builder_installs_block10_target_validator_after_recovery() -> None:
    configure = inspect.getsource(ProductionIsoBuilder.phase_configure)
    helper = inspect.getsource(ProductionIsoBuilder._install_block10_target_validation)
    assert "self._configure_recovery_environment()" in configure
    assert "self._install_block10_target_validation()" in configure
    assert configure.index("self._configure_recovery_environment()") < configure.index(
        "self._install_block10_target_validation()"
    )
    assert "assets/runtime/xaac-block10-validate" in helper
    assert "/usr/local/sbin/xaac-block10-validate" in helper
    assert "target.chmod(0o750)" in helper
    assert "sh -n /usr/local/sbin/xaac-block10-validate" in helper
    assert "root:root:750" in helper


def test_phase_verify_emits_block10_lifecycle_manifest(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    builder.settings = SimpleNamespace(
        output_name="xaac.iso",
        version="1.0.0",
        profile="wyse3040",
        channel="production",
        architecture="amd64",
    )
    builder.dry_run = True
    builder.runner = CommandRunner(builder.paths.logs, dry_run=True)
    builder._save_state = lambda phase: None  # type: ignore[method-assign]
    builder.paths.artifacts.mkdir(parents=True)
    (builder.paths.artifacts / "xaac.iso").write_bytes(b"iso")
    builder.paths.build_root.mkdir(parents=True, exist_ok=True)
    (builder.paths.build_root / "rootfs.squashfs").write_bytes(b"squashfs")

    builder.phase_verify()
    manifest = json.loads((builder.paths.artifacts / "xaac.iso.release.json").read_text())
    assert manifest["schema"] == "xaac-block10-release-manifest/v1"
    assert manifest["lifecycle"] == {
        "update_model": "xaac-update-manifest/v1",
        "transactional_update": True,
        "automatic_rollback": True,
        "boot_recovery": True,
        "factory_reset_enabled": False,
        "release_keyring_provisioned": False,
    }
    assert manifest["validation"]["pre_iso_gate"] == "./scripts/validate-block10-release.sh"
    assert manifest["validation"]["target_command"].endswith("xaac-block10-validate")
    assert manifest["validation"]["physical_validation_required"] is True


def test_phase_verify_records_real_public_keyring_when_provisioned(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    builder.settings = SimpleNamespace(
        output_name="xaac.iso",
        version="1.0.0",
        profile="wyse3040",
        channel="production",
        architecture="amd64",
    )
    builder.dry_run = True
    builder.runner = CommandRunner(builder.paths.logs, dry_run=True)
    builder._save_state = lambda phase: None  # type: ignore[method-assign]
    builder.paths.artifacts.mkdir(parents=True)
    (builder.paths.artifacts / "xaac.iso").write_bytes(b"iso")
    builder.paths.build_root.mkdir(parents=True, exist_ok=True)
    (builder.paths.build_root / "rootfs.squashfs").write_bytes(b"squashfs")
    keyring = builder.paths.rootfs / "usr/share/keyrings/xaac-archive-keyring.gpg"
    keyring.parent.mkdir(parents=True, exist_ok=True)
    keyring.write_bytes(b"real-public-keyring-placeholder-for-test")

    builder.phase_verify()
    manifest = json.loads((builder.paths.artifacts / "xaac.iso.release.json").read_text())
    assert manifest["lifecycle"]["release_keyring_provisioned"] is True


def test_factory_reset_remains_fail_closed_at_block10_closure() -> None:
    policy = yaml.safe_load((ROOT / "config/recovery-environment.yaml").read_text(encoding="utf-8"))
    assert policy["factory_reset"]["enabled"] is False
    assert policy["factory_reset"]["reason"] == "signed_factory_image_not_provisioned"
    assert policy["safety"]["automatic_factory_reset"] is False
    assert policy["safety"]["remote_unattended_factory_reset"] is False


def test_block10_documentation_requires_physical_update_rollback_update_cycle() -> None:
    text = (ROOT / "docs/development/UPDATE_MAINTENANCE_RECOVERY.md").read_text(encoding="utf-8")
    assert "Fase 10.5" in text
    assert "./scripts/validate-block10-release.sh" in text
    assert "./scripts/build-production-iso.sh --clean" in text
    assert "sudo /usr/local/sbin/xaac-block10-validate" in text
    assert "actualització → rollback → actualització" in text
    assert "No es pot donar per validada físicament" in text
