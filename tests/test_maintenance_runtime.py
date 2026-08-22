from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
RUNTIME_PATH = ROOT / "assets/runtime/xaac_maintenance_runtime.py"
CLI_PATH = ROOT / "assets/runtime/xaac-maintenance"


def _load_runtime():
    spec = importlib.util.spec_from_file_location("xaac_maintenance_runtime_test", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy() -> dict:
    import yaml

    data = yaml.safe_load((ROOT / "config/maintenance-diagnostics.yaml").read_text())
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


def test_sanitizer_removes_password_tokens_bearer_and_private_keys() -> None:
    runtime = _load_runtime()
    raw = (
        "normal line\n"
        "password=hunter2\n"
        "Authorization: Bearer abc.def.ghi\n"
        "otp: 123456\n"
        "url=https://alice:secret@example.invalid/api\n"
        "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
    )
    clean = runtime.sanitize_text(raw)
    assert "normal line" in clean
    for secret in ("hunter2", "abc.def.ghi", "123456", "secret@example", "BEGIN PRIVATE KEY"):
        assert secret not in clean
    assert "REDACTED" in clean


def test_health_marks_required_inactive_service_as_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _load_runtime()
    monkeypatch.setattr(runtime, "_disk_usage", lambda: (8_000_000_000, 4_000_000_000, 50))
    monkeypatch.setattr(runtime, "_dpkg_audit", lambda: (True, "net"))

    def fake_run(command, timeout=30):
        if "--failed" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(command)

    def fake_unit(unit):
        if unit == "nftables.service":
            return {"load": "loaded", "active": "inactive", "enabled": "enabled"}
        return {"load": "loaded", "active": "active", "enabled": "enabled"}

    monkeypatch.setattr(runtime, "_run", fake_run)
    monkeypatch.setattr(runtime, "_unit_info", fake_unit)
    text, overall = runtime.health_report(_policy())
    assert overall == "error"
    assert "[ERROR] nftables.service" in text


def test_health_rejects_ssh_inactive_when_remote_management_requires_it(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _load_runtime()
    monkeypatch.setattr(runtime, "_disk_usage", lambda: (8_000_000_000, 4_000_000_000, 50))
    monkeypatch.setattr(runtime, "_dpkg_audit", lambda: (True, "net"))
    monkeypatch.setattr(
        runtime,
        "_run",
        lambda command, timeout=30: subprocess.CompletedProcess(command, 0, "", ""),
    )

    def fake_unit(unit):
        if unit == "ssh.service":
            return {"load": "loaded", "active": "inactive", "enabled": "disabled"}
        return {"load": "loaded", "active": "active", "enabled": "enabled"}

    monkeypatch.setattr(runtime, "_unit_info", fake_unit)
    text, overall = runtime.health_report(_policy())
    assert overall == "error"
    assert "[ERROR] ssh.service" in text


def test_logs_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _load_runtime()
    monkeypatch.setattr(
        runtime,
        "_run",
        lambda command, timeout=30: subprocess.CompletedProcess(
            command, 0, "good line\nOTP=654321\npassword=bad\n", ""
        ),
    )
    text = runtime.logs_report(_policy())
    assert "good line" in text
    assert "654321" not in text
    assert "password=bad" not in text


def test_cleanup_only_removes_expired_named_bundles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _load_runtime()
    diagnostics = tmp_path / "diagnostics"
    diagnostics.mkdir()
    old = diagnostics / "xaac-diagnostics-20200101-000000.tar.gz"
    keep = diagnostics / "xaac-diagnostics-current.tar.gz"
    unrelated = diagnostics / "important.tar.gz"
    for path in (old, keep, unrelated):
        path.write_text("x", encoding="utf-8")
    old_time = time.time() - 30 * 86400
    os.utime(old, (old_time, old_time))
    monkeypatch.setattr(runtime, "DIAGNOSTICS_ROOT", diagnostics)
    monkeypatch.setattr(runtime, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(
        runtime,
        "_run",
        lambda command, timeout=30: subprocess.CompletedProcess(command, 0, "", ""),
    )
    result = runtime.cleanup(_policy())
    assert "1" in result
    assert not old.exists()
    assert keep.exists()
    assert unrelated.exists()


def test_diagnostics_bundle_contains_only_sanitized_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _load_runtime()
    diagnostics = tmp_path / "diagnostics"
    monkeypatch.setattr(runtime, "DIAGNOSTICS_ROOT", diagnostics)
    monkeypatch.setattr(runtime, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(runtime, "UPDATE_STATE_PATHS", ())
    monkeypatch.setattr(runtime, "status_report", lambda policy: "status normal\npassword=never\n")
    monkeypatch.setattr(runtime, "health_report", lambda policy: ("health normal\n", "ok"))
    monkeypatch.setattr(runtime, "network_report", lambda policy: "network token=abcdef\n")
    monkeypatch.setattr(runtime, "storage_report", lambda policy: "storage normal\n")
    monkeypatch.setattr(runtime, "services_report", lambda policy: "services normal\n")
    monkeypatch.setattr(runtime, "logs_report", lambda policy: "logs OTP=123456\n")
    monkeypatch.setattr(
        runtime,
        "_run",
        lambda command, timeout=30: subprocess.CompletedProcess(command, 0, "", ""),
    )
    monkeypatch.setattr(
        runtime,
        "_diagnostic_manifest",
        lambda policy: {
            "schema_version": 1,
            "privacy": {
                "sanitized": True,
                "credentials_included": False,
                "private_keys_included": False,
                "vpn_secrets_included": False,
            },
        },
    )
    bundle = runtime.diagnostics(_policy())
    assert bundle.is_file()
    assert (bundle.stat().st_mode & 0o777) == 0o600
    with tarfile.open(bundle, "r:gz") as archive:
        names = set(archive.getnames())
        assert {"manifest.json", "status.txt", "health.txt", "network.txt", "storage.txt", "services.txt", "logs.txt"} <= names
        combined = b"".join(
            archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile() and archive.extractfile(member) is not None
        ).decode("utf-8")
    assert "never" not in combined
    assert "abcdef" not in combined
    assert "123456" not in combined
    assert "REDACTED" in combined


def test_cli_help_is_available_without_target_policy() -> None:
    result = subprocess.run(
        ["python3", str(CLI_PATH), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "diagnostics" in result.stdout
    assert "cleanup" in result.stdout


def test_storage_reader_tolerates_non_utf8_emmc_vendor_bytes(tmp_path: Path) -> None:
    runtime = _load_runtime()
    attribute = tmp_path / "name"
    attribute.write_bytes(b"HYNIX\xffH8G4a\n")
    value = runtime._read_optional(attribute)
    assert value is not None
    assert value.startswith("HYNIX")
    assert "H8G4a" in value
