from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
ADMIN = ROOT / "assets/runtime/xaac-update-admin"
RUNTIME = ROOT / "assets/runtime/xaac_update_runtime.py"


def _runtime():
    spec = importlib.util.spec_from_file_location("xaac_update_runtime_block10_matrix", RUNTIME)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _admin_policy(tmp_path: Path) -> dict:
    keyring = tmp_path / "keyring.gpg"
    keyring.write_bytes(b"public-keyring")
    return {
        "schema_version": 2,
        "model_id": "xaac-update-architecture-v1",
        "hardware_profile": "wyse3040",
        "architecture": "amd64",
        "channels": [{"id": "production"}],
        "components": [
            {"id": "xaac-thin-client", "package": "xaac-thinclient", "architecture": "all", "critical": True},
            {"id": "xaac-thin-client-vpn", "package": "xaac-thin-client-vpn", "architecture": "all", "critical": True},
            {"id": "xaac-agent", "package": "xaac-agent", "architecture": "amd64", "critical": True},
        ],
        "manifest": {"schema": "xaac-update-manifest/v1", "keyring": str(keyring)},
        "preflight": {
            "require_os_identity": "xaac-thin-client-os",
            "minimum_free_bytes": 536870912,
        },
        "audit": {"path": str(tmp_path / "audit.jsonl")},
    }


def _candidate(namespace: dict, tmp_path: Path, *, schema: str = "xaac-update-manifest/v1") -> tuple[Path, Path]:
    components = []
    definitions = (
        ("xaac-thin-client", "xaac-thinclient", "1.0.1", "all"),
        ("xaac-thin-client-vpn", "xaac-thin-client-vpn", "1.0.1", "all"),
        ("xaac-agent", "xaac-agent", "1.0.1-1", "amd64"),
    )
    for component_id, package, version, architecture in definitions:
        filename = f"{package}_{version}_{architecture}.deb"
        path = tmp_path / filename
        path.write_bytes(f"deb:{package}:{version}".encode())
        components.append(
            {
                "id": component_id,
                "package": package,
                "version": version,
                "architecture": architecture,
                "filename": filename,
                "sha256": namespace["_sha256"](path),
            }
        )
    payload = {
        "schema": schema,
        "release": {
            "os_version": "1.0.0",
            "hardware_profile": "wyse3040",
            "architecture": "amd64",
            "channel": "production",
        },
        "compatibility": {"minimum_installed_os_version": "1.0.0"},
        "components": components,
    }
    payload["integrity"] = {
        "algorithm": "sha256",
        "manifest_payload": namespace["_manifest_payload_hash"](payload),
    }
    manifest = tmp_path / "update-manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    signature = tmp_path / "update-manifest.json.asc"
    signature.write_text("signature", encoding="utf-8")
    return manifest, signature


def _prepare_admin(namespace: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _admin_policy(tmp_path)
    globals_ = namespace["verify_manifest"].__globals__
    monkeypatch.setitem(globals_, "POLICY_PATH", tmp_path / "unused-policy.json")
    monkeypatch.setattr(globals_["os"], "geteuid", lambda: 0)
    monkeypatch.setitem(globals_, "_load_policy", lambda: policy)
    monkeypatch.setitem(globals_, "preflight_payload", lambda: ({"status": "ok", "checks": []}, True))
    monkeypatch.setitem(globals_, "_verify_signature", lambda *_: None)
    monkeypatch.setitem(globals_, "_os_release", lambda: {"ID": "xaac-thin-client-os", "VERSION_ID": "1.0.0"})
    monkeypatch.setitem(globals_, "_compare_versions", lambda *_: True)
    monkeypatch.setitem(globals_, "_installed_version", lambda package: {
        "xaac-thinclient": "1.0.0",
        "xaac-thin-client-vpn": "1.0.0",
        "xaac-agent": "1.0.0-8",
    }[package])
    monkeypatch.setitem(globals_, "_deb_metadata", lambda path: next(
        (item[1], item[2], item[3])
        for item in (
            ("xaac-thin-client", "xaac-thinclient", "1.0.1", "all"),
            ("xaac-thin-client-vpn", "xaac-thin-client-vpn", "1.0.1", "all"),
            ("xaac-agent", "xaac-agent", "1.0.1-1", "amd64"),
        )
        if path.name.startswith(item[1] + "_")
    ))
    monkeypatch.setitem(globals_, "_record_check", lambda *_: None)


def test_preflight_rejects_insufficient_free_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(ADMIN))
    policy = _admin_policy(tmp_path)
    globals_ = namespace["preflight_payload"].__globals__
    monkeypatch.setitem(globals_, "_load_policy", lambda: policy)
    monkeypatch.setitem(globals_, "_os_release", lambda: {"ID": "xaac-thin-client-os"})
    monkeypatch.setitem(globals_, "_architecture", lambda: "amd64")
    monkeypatch.setitem(globals_, "_installed_version", lambda _: "1.0.0")
    monkeypatch.setattr(globals_["shutil"], "disk_usage", lambda _: SimpleNamespace(free=1024))
    monkeypatch.setitem(
        globals_,
        "_run",
        lambda command, **_: subprocess.CompletedProcess(command, 0, "", ""),
    )
    payload, ok = namespace["preflight_payload"]()
    free = next(item for item in payload["checks"] if item["name"] == "free_space")
    assert ok is False
    assert free["ok"] is False


def test_preflight_rejects_dpkg_audit_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(ADMIN))
    policy = _admin_policy(tmp_path)
    globals_ = namespace["preflight_payload"].__globals__
    monkeypatch.setitem(globals_, "_load_policy", lambda: policy)
    monkeypatch.setitem(globals_, "_os_release", lambda: {"ID": "xaac-thin-client-os"})
    monkeypatch.setitem(globals_, "_architecture", lambda: "amd64")
    monkeypatch.setitem(globals_, "_installed_version", lambda _: "1.0.0")
    monkeypatch.setattr(globals_["shutil"], "disk_usage", lambda _: SimpleNamespace(free=2**30))

    def fake_run(command, **_):
        if command[:2] == ["/usr/bin/dpkg", "--audit"]:
            return subprocess.CompletedProcess(command, 0, "package pending configuration\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setitem(globals_, "_run", fake_run)
    payload, ok = namespace["preflight_payload"]()
    audit = next(item for item in payload["checks"] if item["name"] == "dpkg_audit")
    assert ok is False
    assert audit["ok"] is False


def test_manifest_with_wrong_schema_is_rejected_before_package_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(ADMIN))
    _prepare_admin(namespace, tmp_path, monkeypatch)
    manifest, signature = _candidate(namespace, tmp_path, schema="xaac-update-manifest/v999")
    with pytest.raises(namespace["UpdateAdminError"], match="Esquema"):
        namespace["verify_manifest"](manifest, signature, tmp_path)


def test_corrupt_package_sha_is_rejected_before_dpkg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(ADMIN))
    _prepare_admin(namespace, tmp_path, monkeypatch)
    manifest, signature = _candidate(namespace, tmp_path)
    payload = json.loads(manifest.read_text())
    payload["components"][0]["sha256"] = "0" * 64
    payload["integrity"]["manifest_payload"] = namespace["_manifest_payload_hash"](payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(namespace["UpdateAdminError"], match="SHA-256"):
        namespace["verify_manifest"](manifest, signature, tmp_path)


def test_dpkg_install_failure_enters_automatic_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime()
    candidate = {
        "release": {"os_version": "1.0.0"},
        "components": [{"package": "xaac-thinclient", "version": "1.0.1", "filename": "client.deb", "sha256": "a" * 64}],
    }
    policy = {
        "staging": {"root": str(tmp_path / "staging"), "preserve_on_success": False},
        "recovery_point": {"root": str(tmp_path / "recovery"), "package_cache": str(tmp_path / "cache"), "max_points": 2, "configuration_paths": []},
        "installation": {"lock_timeout_seconds": 30},
        "health": {"timeout_seconds": 30},
    }
    staging = tmp_path / "staging" / "tx"
    staging.mkdir(parents=True)
    (staging / "client.deb").write_bytes(b"deb")
    recovery = tmp_path / "recovery" / "tx"
    recovery.mkdir(parents=True)
    monkeypatch.setattr(runtime, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(runtime, "ROLLBACK_STATE_PATH", tmp_path / "rollback.json")
    monkeypatch.setattr(runtime, "BLOCKED_PATH", tmp_path / "blocked.json")
    monkeypatch.setattr(runtime, "load_policy", lambda: policy)
    monkeypatch.setattr(runtime, "_lock", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(runtime, "_transaction_id", lambda: "tx")
    monkeypatch.setattr(runtime, "_copy_verified_bundle", lambda *_: (staging, candidate))
    monkeypatch.setattr(runtime, "is_blocked", lambda *_: False)
    monkeypatch.setattr(runtime, "_snapshot_runtime_state", lambda *_: {"thin_client_running": False, "agent_active": False, "vpn_manager_active": False})
    monkeypatch.setattr(runtime, "_create_recovery_point", lambda *_: (recovery, {"packages": [{"package": "xaac-thinclient", "version": "1.0.0"}]}))
    monkeypatch.setattr(runtime, "installed_version", lambda _: "1.0.0")
    monkeypatch.setattr(runtime, "_install_debs", lambda *_: (_ for _ in ()).throw(runtime.UpdateRuntimeError("dpkg failed")))
    rollbacks: list[str] = []
    monkeypatch.setattr(runtime, "_rollback_from_recovery", lambda *_args, **_kwargs: rollbacks.append("rollback") or {"status": "rolled_back"})
    monkeypatch.setattr(runtime, "_block_failed", lambda *_: None)
    with pytest.raises(runtime.UpdateRuntimeError, match="dpkg failed"):
        runtime.apply_update(tmp_path / "manifest", tmp_path / "sig", tmp_path)
    assert rollbacks == ["rollback"]
    assert json.loads((tmp_path / "state.json").read_text())["status"] == "rolled_back"


def test_corrupt_configuration_backup_is_never_restored(tmp_path: Path) -> None:
    runtime = _runtime()
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    archive = recovery / "configuration.tar"
    archive.write_bytes(b"corrupt")
    with pytest.raises(runtime.UpdateRuntimeError, match="corrupte"):
        runtime._restore_configuration(recovery, {"archive": archive.name, "sha256": "0" * 64})


def test_interrupted_transaction_is_rolled_back_on_recovery_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime()
    recovery = tmp_path / "recovery" / "tx"
    recovery.mkdir(parents=True)
    (recovery / "recovery-point.json").write_text(
        json.dumps({"transaction_id": "tx", "packages": [{"package": "xaac-thinclient", "version": "1.0.0"}]}),
        encoding="utf-8",
    )
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"status": "installing", "transaction_id": "tx", "recovery_point": str(recovery)}), encoding="utf-8")
    monkeypatch.setattr(runtime, "STATE_PATH", state)
    monkeypatch.setattr(runtime, "load_policy", lambda: {"recovery_point": {"root": str(tmp_path / "recovery")}})
    monkeypatch.setattr(runtime, "_lock", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(runtime, "unit_exists", lambda _: False)
    monkeypatch.setattr(runtime, "unit_active", lambda _: False)
    monkeypatch.setattr(runtime, "_rollback_from_recovery", lambda *_args, **_kwargs: {"status": "rolled_back"})
    result = runtime.recover_interrupted()
    assert result == {"status": "rolled_back"}
    assert json.loads(state.read_text())["status"] == "rolled_back_after_interruption"


def test_update_and_recovery_paths_do_not_depend_on_network_downloads() -> None:
    source = (ADMIN.read_text(encoding="utf-8") + "\n" + RUNTIME.read_text(encoding="utf-8")).lower()
    for forbidden in ("curl ", "wget ", "apt download", "apt-get install"):
        assert forbidden not in source
