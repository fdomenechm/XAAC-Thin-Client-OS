from __future__ import annotations

import runpy
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


def test_confirmation_is_checked_before_root_privileges(monkeypatch, tmp_path: Path, capsys) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    monkeypatch.setattr(namespace["os"], "geteuid", lambda: 1000)

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    assert namespace["main"](["update", str(manifest)]) == 2
    update_error = capsys.readouterr().err
    assert "--yes" in update_error
    assert "sudo" not in update_error

    assert namespace["main"](["rollback"]) == 2
    rollback_error = capsys.readouterr().err
    assert "--yes" in rollback_error
    assert "sudo" not in rollback_error


def test_root_privileges_are_required_after_confirmation(monkeypatch, tmp_path: Path, capsys) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    monkeypatch.setattr(namespace["os"], "geteuid", lambda: 1000)

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    assert namespace["main"](["update", str(manifest), "--yes"]) == 2
    update_error = capsys.readouterr().err
    assert "sudo" in update_error

    assert namespace["main"](["rollback", "--yes"]) == 2
    rollback_error = capsys.readouterr().err
    assert "sudo" in rollback_error


def test_os_update_requires_confirmation_before_root_privileges(monkeypatch, capsys) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    monkeypatch.setattr(namespace["os"], "geteuid", lambda: 1000)

    assert namespace["main"](["os-update"]) == 2
    first = capsys.readouterr().err
    assert "--yes" in first
    assert "sudo" not in first

    assert namespace["main"](["os-update", "--yes"]) == 2
    second = capsys.readouterr().err
    assert "sudo" in second


def test_update_admin_exposes_phase_10_6_commands() -> None:
    result = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "os-status" in result.stdout
    assert "os-check" in result.stdout
    assert "os-update" in result.stdout
