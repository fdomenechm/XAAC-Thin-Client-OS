from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
RUNTIME_PATH = ROOT / "assets/runtime/xaac_recovery_runtime.py"
CLI_PATH = ROOT / "assets/runtime/xaac-recovery"


def _load_runtime():
    spec = importlib.util.spec_from_file_location("xaac_recovery_runtime_test", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy() -> dict:
    data = yaml.safe_load((ROOT / "config/recovery-environment.yaml").read_text(encoding="utf-8"))
    data.pop("outputs")
    return data


def test_runtime_assets_compile() -> None:
    result = subprocess.run(
        ["python3", "-m", "py_compile", str(CLI_PATH), str(RUNTIME_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert CLI_PATH.stat().st_mode & 0o111


def test_recovery_mode_requires_exact_kernel_token(tmp_path: Path) -> None:
    runtime = _load_runtime()
    cmdline = tmp_path / "cmdline"
    cmdline.write_text("quiet systemd.unit=xaac-recovery.target ro\n", encoding="utf-8")
    assert runtime.in_recovery_mode(cmdline) is True
    cmdline.write_text("quiet systemd.unit=graphical.target ro\n", encoding="utf-8")
    assert runtime.in_recovery_mode(cmdline) is False


def test_repair_fails_closed_outside_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _load_runtime()
    monkeypatch.setattr(runtime, "in_recovery_mode", lambda: False)
    with pytest.raises(runtime.RecoveryRuntimeError, match="només està permesa"):
        runtime.repair_system()


def test_configuration_restore_fails_closed_outside_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _load_runtime()
    monkeypatch.setattr(runtime, "in_recovery_mode", lambda: False)
    with pytest.raises(runtime.RecoveryRuntimeError, match="només està permesa"):
        runtime.restore_configuration()


def test_repair_runs_dpkg_initramfs_and_grub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _load_runtime()
    state = tmp_path / "state.json"
    audit = tmp_path / "audit" / "recovery.jsonl"
    grub = tmp_path / "grub.cfg"
    grub.write_text(
        "menuentry 'XAAC Thin Client OS' {}\n"
        "menuentry 'XAAC Thin Client OS — Recovery' {}\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(command, timeout=300, check=False, env=None):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runtime, "STATE_PATH", state)
    monkeypatch.setattr(runtime, "AUDIT_PATH", audit)
    monkeypatch.setattr(runtime, "in_recovery_mode", lambda: True)
    monkeypatch.setattr(runtime, "load_policy", _policy)
    monkeypatch.setattr(runtime, "_run", fake_run)
    monkeypatch.setattr(runtime, "_dpkg_audit", lambda: (True, ""))

    original_path = Path

    class FakePath(type(Path())):
        pass

    # Patch only the specific grub lookup while preserving normal Path behavior.
    monkeypatch.setattr(runtime, "Path", lambda value: grub if value == "/boot/grub/grub.cfg" else original_path(value))
    result = runtime.repair_system()
    assert result["status"] == "repaired"
    assert ["/usr/bin/dpkg", "--configure", "-a"] in calls
    assert ["/usr/sbin/update-initramfs", "-u", "-k", "all"] in calls
    assert ["/usr/sbin/update-grub"] in calls
    assert json.loads(state.read_text())["last_action"] == "repair"
    assert "repair_completed" in audit.read_text()


def test_network_change_is_explicit_and_recovery_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _load_runtime()
    calls: list[list[str]] = []
    monkeypatch.setattr(runtime, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(runtime, "AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(runtime, "in_recovery_mode", lambda: True)
    monkeypatch.setattr(runtime, "load_policy", _policy)

    def fake_run(command, timeout=300, check=False, env=None):
        calls.append(command)
        if command[:3] == ["/usr/bin/systemctl", "is-active", "--quiet"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runtime, "_run", fake_run)
    assert runtime.set_network(True)["status"] == "active"
    assert ["/usr/bin/systemctl", "start", "NetworkManager.service"] in calls


def test_cli_requires_confirmation_before_privileges() -> None:
    text = CLI_PATH.read_text(encoding="utf-8")
    assert "_require_yes(bool(args.yes))" in text
    assert text.index("_require_yes(bool(args.yes))") < text.index("_require_root()", text.index("def main"))


def test_cli_help_does_not_require_target_policy() -> None:
    result = subprocess.run(["python3", str(CLI_PATH), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "rollback" in result.stdout
    assert "repair" in result.stdout
    assert "network-on" in result.stdout
