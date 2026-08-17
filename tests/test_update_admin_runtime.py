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


def test_update_admin_exposes_phase_10_1_commands() -> None:
    result = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "status" in result.stdout
    assert "preflight" in result.stdout
    assert "check" in result.stdout
    assert "update" in result.stdout


def test_update_command_is_explicitly_non_destructive_in_phase_10_1() -> None:
    result = subprocess.run([str(SCRIPT), "update"], capture_output=True, text=True)
    assert result.returncode == 64
    assert "fase 10.2" in result.stderr
