from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
RUNTIME_PATH = ROOT / "assets/runtime/xaac_update_runtime.py"


def load_runtime() -> ModuleType:
    spec = importlib.util.spec_from_file_location("xaac_update_runtime_test", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def policy(tmp_path: Path) -> dict:
    return {
        "schema_version": 2,
        "transaction_id": "xaac-transactional-update",
        "staging": {
            "root": str(tmp_path / "staging"),
            "maximum_bundle_bytes": 268435456,
            "preserve_on_success": False,
        },
        "recovery_point": {
            "root": str(tmp_path / "recovery"),
            "package_cache": str(tmp_path / "cache"),
            "max_points": 2,
            "configuration_paths": [],
        },
        "installation": {"lock_timeout_seconds": 300},
        "health": {"timeout_seconds": 30},
    }


def manifest() -> dict:
    return {
        "release": {"os_version": "1.0.0"},
        "components": [
            {
                "id": "xaac-thin-client",
                "package": "xaac-thinclient",
                "version": "1.0.1",
                "filename": "xaac-thinclient_1.0.1_all.deb",
                "sha256": "a" * 64,
            },
            {
                "id": "xaac-thin-client-vpn",
                "package": "xaac-thin-client-vpn",
                "version": "0.5.3-1",
                "filename": "xaac-thin-client-vpn_0.5.3-1_all.deb",
                "sha256": "b" * 64,
            },
            {
                "id": "xaac-agent",
                "package": "xaac-agent",
                "version": "1.0.1-1",
                "filename": "xaac-agent_1.0.1-1_amd64.deb",
                "sha256": "c" * 64,
            },
        ],
    }


def test_runtime_is_stdlib_only_and_compiles() -> None:
    source = RUNTIME_PATH.read_text()
    assert "import yaml" not in source
    compile(source, str(RUNTIME_PATH), "exec")


def test_safe_relative_filename_rejects_traversal() -> None:
    runtime = load_runtime()
    assert runtime.safe_relative_filename("package.deb") == "package.deb"
    with pytest.raises(runtime.UpdateRuntimeError):
        runtime.safe_relative_filename("../package.deb")
    with pytest.raises(runtime.UpdateRuntimeError):
        runtime.safe_relative_filename("subdir/package.deb")


def test_atomic_json_rejects_symlink_destination(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "state.json"
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(runtime.UpdateRuntimeError, match="symlink"):
        runtime.atomic_json(target, {"status": "idle"})


def test_package_cache_sanitises_debian_epoch(tmp_path: Path) -> None:
    runtime = load_runtime()
    path = runtime.package_cache_path(policy(tmp_path), "xaac-agent", "1:2.0-1")
    assert path.name == "1_2.0-1.deb"
    assert path.parent.name == "xaac-agent"


def test_blocked_registry_matches_exact_component_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = load_runtime()
    blocked = tmp_path / "blocked.json"
    monkeypatch.setattr(runtime, "BLOCKED_PATH", blocked)
    candidate = manifest()
    runtime._block_failed(candidate, "tx-1", "health check failed")
    assert runtime.is_blocked(candidate) is True
    changed = manifest()
    changed["components"][0]["version"] = "1.0.2"
    assert runtime.is_blocked(changed) is False


class DummyLock:
    def close(self) -> None:
        pass


def configure_simulated_transaction(
    runtime: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    health_ok: bool,
) -> tuple[dict[str, str], list[str]]:
    candidate = manifest()
    pol = policy(tmp_path)
    staging = tmp_path / "staging" / "tx"
    staging.mkdir(parents=True)
    for item in candidate["components"]:
        (staging / item["filename"]).write_bytes(b"deb")
    recovery = tmp_path / "recovery" / "tx"
    recovery.mkdir(parents=True)
    previous = {
        "xaac-thinclient": "1.0.0",
        "xaac-thin-client-vpn": "0.5.2~dev1-1",
        "xaac-agent": "1.0.0-8",
    }
    current = dict(previous)
    events: list[str] = []
    monkeypatch.setattr(runtime, "CURRENT_RELEASE_PATH", tmp_path / "current-release.json")
    monkeypatch.setattr(runtime, "STATE_PATH", tmp_path / "transaction-state.json")
    monkeypatch.setattr(runtime, "ROLLBACK_STATE_PATH", tmp_path / "rollback-state.json")
    monkeypatch.setattr(runtime, "BLOCKED_PATH", tmp_path / "blocked.json")
    monkeypatch.setattr(runtime, "load_policy", lambda: pol)
    monkeypatch.setattr(runtime, "_lock", lambda: DummyLock())
    monkeypatch.setattr(runtime, "_transaction_id", lambda: "tx-test")
    monkeypatch.setattr(runtime, "_copy_verified_bundle", lambda *_: (staging, candidate))
    monkeypatch.setattr(runtime, "is_blocked", lambda *_: False)
    monkeypatch.setattr(runtime, "_snapshot_runtime_state", lambda *_: {"thin_client_running": False, "agent_active": False, "vpn_manager_active": False})
    monkeypatch.setattr(
        runtime,
        "_create_recovery_point",
        lambda *_: (
            recovery,
            {"packages": [{"package": name, "version": version} for name, version in previous.items()]},
        ),
    )
    monkeypatch.setattr(runtime, "installed_version", lambda package: current.get(package))

    def install(_paths, packages, _timeout):
        for item in candidate["components"]:
            if item["package"] in packages:
                current[item["package"]] = item["version"]

    monkeypatch.setattr(runtime, "_install_debs", install)
    monkeypatch.setattr(runtime, "_restart_changed", lambda changed, before: sorted(changed))
    monkeypatch.setattr(runtime, "_health_check", lambda expected, before, timeout: ({"simulated": {"ok": health_ok}}, health_ok))
    monkeypatch.setattr(runtime, "_cache_candidates", lambda *_: events.append("cached"))
    monkeypatch.setattr(runtime, "_prune_recovery_points", lambda *_args, **_kwargs: events.append("pruned"))
    def fake_copy2(source, target, **_kwargs):
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(Path(source).read_bytes() if Path(source).exists() else b"manifest")
        return str(target_path)

    monkeypatch.setattr(runtime.shutil, "copy2", fake_copy2)
    monkeypatch.setattr(runtime.shutil, "rmtree", lambda *_args, **_kwargs: events.append("staging-cleaned"))
    return current, events


def test_apply_update_confirms_only_after_health_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = load_runtime()
    current, events = configure_simulated_transaction(runtime, tmp_path, monkeypatch, health_ok=True)
    result = runtime.apply_update(tmp_path / "manifest", tmp_path / "signature", tmp_path / "bundle")
    assert result["status"] == "confirmed"
    assert current == {
        "xaac-thinclient": "1.0.1",
        "xaac-thin-client-vpn": "0.5.3-1",
        "xaac-agent": "1.0.1-1",
    }
    assert "cached" in events
    assert "pruned" in events
    assert json.loads((tmp_path / "transaction-state.json").read_text())["status"] == "confirmed"


def test_failed_health_check_triggers_automatic_rollback_and_blocks_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime()
    configure_simulated_transaction(runtime, tmp_path, monkeypatch, health_ok=False)
    rollback_calls: list[str] = []
    block_calls: list[str] = []
    monkeypatch.setattr(
        runtime,
        "_rollback_from_recovery",
        lambda policy, recovery, before, cause: rollback_calls.append(cause) or {"status": "rolled_back"},
    )
    monkeypatch.setattr(runtime, "_block_failed", lambda manifest, txid, reason: block_calls.append(txid))
    with pytest.raises(runtime.UpdateRuntimeError, match="health-check"):
        runtime.apply_update(tmp_path / "manifest", tmp_path / "signature", tmp_path / "bundle")
    state = json.loads((tmp_path / "transaction-state.json").read_text())
    assert state["status"] == "rolled_back"
    assert rollback_calls
    assert block_calls == ["tx-test"]


def test_recovery_service_is_before_kiosk_and_uses_transaction_runtime() -> None:
    from xaac_thin_client_os.transactional_update import create_transactional_update_plan, TransactionalUpdateInstaller

    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        rootfs = Path(directory) / "rootfs"
        rootfs.mkdir()
        plan = create_transactional_update_plan(rootfs, ROOT / "config/transactional-update.yaml")
        _, _, service, _ = TransactionalUpdateInstaller().install(plan)
        text = service.read_text()
        assert "Before=greetd.service" in text
        assert "xaac_update_runtime.py recover-interrupted" in text
        assert "ProtectSystem=no" in text
