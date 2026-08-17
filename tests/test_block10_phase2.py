from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_phase_10_2_runtime_assets_exist_and_compile() -> None:
    admin = ROOT / "assets/runtime/xaac-update-admin"
    runtime = ROOT / "assets/runtime/xaac_update_runtime.py"
    assert admin.is_file() and admin.stat().st_mode & 0o111
    assert runtime.is_file()
    result = subprocess.run(
        ["python3", "-m", "py_compile", str(admin), str(runtime)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_phase_10_2_declares_required_runtime_packages() -> None:
    packages = yaml.safe_load((ROOT / "config/packages.yaml").read_text())
    assert "gpgv" in packages["base"]
    assert "procps" in packages["base"]


def test_phase_10_2_preserves_actual_xaac_configuration() -> None:
    policy = yaml.safe_load((ROOT / "config/transactional-update.yaml").read_text())
    paths = set(policy["recovery_point"]["configuration_paths"])
    assert "/etc/xaac" in paths
    assert "/etc/xaac-agent" in paths
    assert "/etc/xaac-thinclient" in paths
    assert "/etc/NetworkManager/system-connections" in paths
    assert policy["recovery_point"]["max_points"] == 2


def test_phase_10_2_release_scripts_are_posix_sh() -> None:
    for name in ("provision-update-keyring.sh", "build-update-bundle.sh", "validate-block10-phase2.sh"):
        path = ROOT / "scripts" / name
        assert path.read_text().startswith("#!/bin/sh\n")
        result = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_repository_contains_no_private_release_key() -> None:
    for path in (ROOT / "assets/release").rglob("*"):
        if path.is_file():
            assert "BEGIN PGP PRIVATE KEY BLOCK" not in path.read_text(errors="ignore")
    assert not (ROOT / "assets/release/xaac-archive-keyring.gpg").exists()


def test_production_builder_integrates_transaction_and_baseline_rollback_cache() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text()
    assert "create_transactional_update_plan" in source
    assert "create_package_rollback_plan" in source
    assert "package_cache" in source
    assert "xaac-update-recover.service" in source
    assert "assets/release/xaac-archive-keyring.gpg" in source
    assert "Falta el paquet base de rollback" in source


def test_admin_cli_exposes_transaction_and_manual_rollback() -> None:
    script = ROOT / "assets/runtime/xaac-update-admin"
    result = subprocess.run([str(script), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "update" in result.stdout
    assert "rollback" in result.stdout
    assert "--yes" in subprocess.run([str(script), "update", "--help"], capture_output=True, text=True).stdout


def test_phase_10_2_documentation_is_closed_without_iso() -> None:
    text = (ROOT / "docs/phases/block-10/phase-10-02.md").read_text()
    assert "rollback automàtic" in text
    assert "xaac-update-recover.service" in text
    assert "No cal generar ISO" in text
    assert "no entra mai al repositori ni a la ISO" in text
