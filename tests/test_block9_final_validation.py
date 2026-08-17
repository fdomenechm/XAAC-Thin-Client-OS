from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from xaac_thin_client_os.production_builder import BuildPaths, CommandRunner, ProductionIsoBuilder


ROOT = Path(__file__).resolve().parents[1]


def _minimal_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='xaac-test'\nversion='0'\n", encoding="utf-8")
    return root


def test_block94_release_gate_is_the_single_prebuild_gate() -> None:
    build = (ROOT / "scripts/build-production-iso.sh").read_text(encoding="utf-8")
    gate = (ROOT / "scripts/validate-block9-release.sh").read_text(encoding="utf-8")

    assert '"$PROJECT_ROOT/scripts/validate-block9-release.sh"' in build
    assert 'XAAC_RELEASE_GATE_PASSED' in build
    assert '--preserve-env=PYTHON,XAAC_RELEASE_GATE_PASSED' in build
    assert '"$PROJECT_ROOT/scripts/validate-block7-release.sh"' not in build
    assert '"$PROJECT_ROOT/scripts/validate-block7-integration.sh"' not in build
    assert '"$PROJECT_ROOT/scripts/validate-block7-release.sh"' in gate
    assert '"$PROJECT_ROOT/scripts/validate-block7-integration.sh"' in gate
    assert '"$PROJECT_ROOT/scripts/validate-block8-visual.sh"' in gate
    assert '"$PROJECT_ROOT/scripts/validate-block9-hardening.sh"' in gate
    assert '"$PYTHON" -m pytest -q' in gate


def test_block94_release_gate_validates_only_effective_production_debs() -> None:
    gate = (ROOT / "scripts/validate-block9-release.sh").read_text(encoding="utf-8")

    for artifact in (
        "packages/xaac-agent_1.0.0-8_amd64.deb",
        "packages/xaac-thin-client-vpn_0.5.2~dev1-1_all.deb",
        "packages/xaac-thinclient_1.0.0_all.deb",
    ):
        assert artifact in gate
    assert "dpkg-deb --info" in gate


def test_block94_target_validator_is_read_only_and_checks_effective_hardening() -> None:
    target = (ROOT / "assets/runtime/xaac-block9-validate").read_text(encoding="utf-8")

    for expected in (
        "Wyse 3040",
        "XAAC_ROOT",
        "RAM >= 1800 MiB",
        "idle RAM <= 650 MiB",
        "root free >= 512 MiB",
        "root noatime",
        "zram0 present",
        "zram uses zstd",
        "swappiness=100",
        "journald volatile",
        "fstrim enabled",
        "SSH disabled at boot",
        "nftables active",
        "greetd active",
        "xaac-vpn-manager.service",
        "AppArmor agent profile",
        "Thin Client running",
        "no failed systemd units",
        "AppArmor DENIED events",
        "boot <= 45 s",
    ):
        assert expected in target

    forbidden = (
        "systemctl enable",
        "systemctl start",
        "systemctl restart",
        "sysctl -w",
        "apparmor_parser -r",
        "apparmor_parser -a",
        "aa-enforce",
    )
    assert not any(command in target for command in forbidden)


def test_production_builder_installs_block94_target_gate() -> None:
    configure = inspect.getsource(ProductionIsoBuilder.phase_configure)
    helper = inspect.getsource(ProductionIsoBuilder._install_block9_target_validation)

    assert "self._install_block9_target_validation()" in configure
    assert "assets/runtime/xaac-block9-validate" in helper
    assert "/usr/local/sbin/xaac-block9-validate" in helper
    assert "target.chmod(0o750)" in helper
    assert "sh -n /usr/local/sbin/xaac-block9-validate" in helper
    assert "root:root:750" in helper


def test_phase_verify_writes_traceable_block94_release_manifest(tmp_path: Path) -> None:
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
    iso = builder.paths.artifacts / "xaac.iso"
    iso.write_bytes(b"iso-release-candidate")
    builder.paths.build_root.mkdir(parents=True, exist_ok=True)
    (builder.paths.build_root / "rootfs.squashfs").write_bytes(b"squashfs-release-candidate")

    builder.phase_verify()

    manifest = json.loads((builder.paths.artifacts / "xaac.iso.release.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "xaac-block9-release-manifest/v1"
    assert manifest["version"] == "1.0.0"
    assert manifest["profile"] == "wyse3040"
    assert manifest["iso"]["name"] == "xaac.iso"
    assert len(manifest["iso"]["sha256"]) == 64
    assert len(manifest["squashfs"]["sha256"]) == 64
    assert manifest["validation"] == {
        "target_command": "sudo /usr/local/sbin/xaac-block9-validate",
        "apparmor_mode": "complain-review-required",
    }


def test_block94_documentation_defines_single_iso_and_physical_gate() -> None:
    text = (ROOT / "docs/development/HARDENING_OPTIMIZATION.md").read_text(encoding="utf-8")

    assert "Fase 9.4 implementada" in text
    assert "./scripts/validate-block9-release.sh" in text
    assert "./scripts/build-production-iso.sh --clean" in text
    assert "sudo /usr/local/sbin/xaac-block9-validate" in text
    assert "AppArmor" in text and "DENIED" in text
