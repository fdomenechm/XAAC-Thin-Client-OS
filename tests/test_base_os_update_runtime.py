from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
RUNTIME = ROOT / "assets/runtime/xaac_base_os_update_runtime.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("xaac_base_os_update_runtime_test", RUNTIME)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def policy() -> dict:
    return {
        "schema_version": 1,
        "update_id": "xaac-base-os-update",
        "phase": "10.6",
        "hardware_profile": "wyse3040",
        "platform": {"debian_major": 13, "suite": "trixie", "architecture": "amd64"},
        "policy": {
            "allow_release_change": False,
            "allow_downgrade": False,
            "allow_removals": False,
            "automatic_reboot": False,
            "automatic_rollback": False,
            "maximum_changed_packages": 256,
            "maximum_new_packages": 48,
            "protected_packages": ["xaac-thinclient", "xaac-thin-client-vpn", "xaac-agent"],
            "reboot_package_prefixes": ["linux-image", "systemd", "libc6"],
            "minimum_free_after_download_bytes": 1,
        },
        "health": {"required_services": [], "installed_services": []},
        "outputs": {
            "state": "/tmp/state.json",
            "audit": "/tmp/audit.jsonl",
            "checkpoint": "/tmp/checkpoint",
        },
    }


def test_parse_plan_distinguishes_upgrade_new_and_removal() -> None:
    runtime = load_runtime()
    parsed = runtime.parse_plan(
        "Inst systemd [257.1-1] (257.2-1 Debian:13 [amd64])\n"
        "Inst linux-image-6.12.1-amd64 (6.12.1-2 Debian:13 [amd64])\n"
        "Remv old-package [1.0]\n"
    )
    assert parsed["changes"][0]["installed"] == "257.1-1"
    assert parsed["changes"][1]["new"] is True
    assert parsed["removals"][0]["package"] == "old-package"


def test_validate_plan_blocks_any_removal() -> None:
    runtime = load_runtime()
    with pytest.raises(runtime.BaseOsRuntimeError, match="eliminar"):
        runtime.validate_plan(policy(), {"changes": [], "removals": [{"package": "x"}]})


def test_validate_plan_blocks_xaac_packages() -> None:
    runtime = load_runtime()
    plan = {
        "changes": [
            {"package": "xaac-agent", "base_package": "xaac-agent", "installed": "1", "candidate": "2", "new": False}
        ],
        "removals": [],
    }
    with pytest.raises(runtime.BaseOsRuntimeError, match="protegits"):
        runtime.validate_plan(policy(), plan)


def test_validate_plan_blocks_downgrade(monkeypatch) -> None:
    runtime = load_runtime()
    monkeypatch.setattr(runtime, "_dpkg_compare", lambda left, relation, right: False)
    plan = {
        "changes": [
            {"package": "systemd", "base_package": "systemd", "installed": "257.2", "candidate": "257.1", "new": False}
        ],
        "removals": [],
    }
    with pytest.raises(runtime.BaseOsRuntimeError, match="Downgrade"):
        runtime.validate_plan(policy(), plan)


def test_validate_plan_marks_kernel_or_systemd_for_reboot(monkeypatch) -> None:
    runtime = load_runtime()
    monkeypatch.setattr(runtime, "_dpkg_compare", lambda left, relation, right: True)
    plan = {
        "changes": [
            {"package": "linux-image-amd64", "base_package": "linux-image-amd64", "installed": "1", "candidate": "2", "new": False}
        ],
        "removals": [],
    }
    result = runtime.validate_plan(policy(), plan)
    assert result["status"] == "available"
    assert result["reboot_recommended"] is True
    assert result["removals"] == 0


def test_simulation_never_uses_full_or_dist_upgrade(monkeypatch) -> None:
    runtime = load_runtime()
    seen = []
    monkeypatch.setattr(runtime, "_run", lambda command, **kwargs: seen.append(command) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    runtime._simulate()
    command = seen[0]
    assert "upgrade" in command
    assert "--with-new-pkgs" in command
    assert "--no-remove" in command
    assert "full-upgrade" not in command
    assert "dist-upgrade" not in command


def test_install_is_offline_after_download_and_preserves_local_conffiles(monkeypatch) -> None:
    runtime = load_runtime()
    seen = []
    monkeypatch.setattr(runtime, "_run", lambda command, **kwargs: seen.append(command) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    runtime._install()
    command = seen[0]
    assert "--no-download" in command
    assert "--no-remove" in command
    assert "--with-new-pkgs" in command
    assert "Dpkg::Options::=--force-confold" in command


def test_plan_fingerprint_is_deterministic() -> None:
    runtime = load_runtime()
    payload = {
        "packages": [
            {"package": "systemd", "installed": "1", "candidate": "2", "new": False},
            {"package": "linux-image-x", "installed": None, "candidate": "3", "new": True},
        ]
    }
    assert runtime._plan_fingerprint(payload) == runtime._plan_fingerprint(payload)


def test_post_health_requires_every_approved_candidate_version(monkeypatch) -> None:
    runtime = load_runtime()
    p = policy()
    p["health"] = {"required_services": [], "installed_services": []}
    plan = {
        "packages": [
            {"package": "systemd", "candidate": "257.2"},
            {"package": "libc6", "candidate": "2.41"},
        ]
    }
    monkeypatch.setattr(runtime, "_installed_version", lambda package: "257.2" if package == "systemd" else "2.40")
    monkeypatch.setattr(runtime, "validate_sources", lambda policy: {"ok": True})
    monkeypatch.setattr(
        runtime,
        "_run",
        lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    health, ok = runtime._post_health(p, plan)
    assert ok is False
    libc = next(item for item in health["checks"] if item["name"] == "package:libc6")
    assert libc["expected"] == "2.41"
    assert libc["actual"] == "2.40"
