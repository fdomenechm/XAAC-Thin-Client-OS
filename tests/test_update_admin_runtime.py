from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "assets/runtime/xaac-update-admin"


def test_update_admin_is_executable_and_valid_python() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111
    result = subprocess.run(["python3", "-m", "py_compile", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_update_admin_exposes_phase_10_2_commands() -> None:
    result = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "status" in result.stdout
    assert "preflight" in result.stdout
    assert "check" in result.stdout
    assert "update" in result.stdout
    assert "rollback" in result.stdout


def test_update_command_requires_a_manifest_and_explicit_confirmation() -> None:
    result = subprocess.run([str(SCRIPT), "update"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "manifest" in result.stderr


def test_update_command_requires_yes_before_transaction(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    result = subprocess.run([str(SCRIPT), "update", str(manifest)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "--yes" in result.stderr


def test_rollback_requires_explicit_confirmation() -> None:
    result = subprocess.run([str(SCRIPT), "rollback"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "--yes" in result.stderr
