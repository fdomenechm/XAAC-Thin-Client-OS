from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.policy_application import (
    PolicyApplicationError,
    PolicyApplicationManager,
    load_policy_application_profile,
    policy_digest,
    validate_policy_document,
)


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "policy-application.yaml"
    path.write_text(Path("config/policy-application.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _document(policy_id: str = "office-default", revision: int = 1, **payload: object) -> dict[str, object]:
    actual = payload or {"kiosk": {"allow_shutdown": False}}
    return {
        "schema_version": 1,
        "format": "xaac-device-policy",
        "policy_id": policy_id,
        "revision": revision,
        "payload": actual,
        "sha256": policy_digest(actual),
    }


def test_profile_requires_transactional_rollback() -> None:
    profile = load_policy_application_profile(Path("config/policy-application.yaml"))
    assert profile["transaction"]["rollback_on_apply_failure"] is True
    assert profile["policy"]["require_digest"] is True


def test_profile_rejects_disabled_rollback(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/policy-application.yaml").read_text())
    data["transaction"]["rollback_on_apply_failure"] = False
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(PolicyApplicationError, match="rollback"):
        load_policy_application_profile(path)


def test_document_validation_accepts_known_sections() -> None:
    profile = load_policy_application_profile(Path("config/policy-application.yaml"))
    document = _document(network={"dhcp": True}, client={"server": "rdp.example"})
    assert validate_policy_document(document, profile) == document


def test_document_validation_rejects_unknown_section() -> None:
    profile = load_policy_application_profile(Path("config/policy-application.yaml"))
    with pytest.raises(PolicyApplicationError, match="no autoritzades"):
        validate_policy_document(_document(shell={"command": "id"}), profile)


def test_document_validation_rejects_modified_payload() -> None:
    profile = load_policy_application_profile(Path("config/policy-application.yaml"))
    document = _document()
    document["payload"] = {"kiosk": {"allow_shutdown": True}}
    with pytest.raises(PolicyApplicationError, match="SHA-256"):
        validate_policy_document(document, profile)


def test_installer_dry_run_does_not_write(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    root.mkdir()
    paths = PolicyApplicationManager(root, _profile(tmp_path)).install(dry_run=True)
    assert len(paths) == 6
    assert not (root / "etc/xaac/policy-application.yaml").exists()


def test_installer_writes_configuration_state_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    root.mkdir()
    paths = PolicyApplicationManager(root, _profile(tmp_path)).install()
    assert paths[0].is_file()
    assert paths[1].is_dir()
    assert paths[4].is_file()
    assert paths[5].is_file()
    state = json.loads((root / "var/lib/xaac-agent/policies/state.json").read_text())
    assert state["status"] == "idle"
    manifest = json.loads((root / "etc/xaac/policy-application-manifest.json").read_text())
    assert manifest["transactional"] is True


def test_stage_apply_and_confirm_policy(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    root.mkdir()
    manager = PolicyApplicationManager(root, _profile(tmp_path))
    manager.install()
    staged = manager.stage(_document())
    active = manager.apply(staged)
    manager.confirm()
    assert json.loads(active.read_text())["policy_id"] == "office-default"
    state = json.loads((root / "var/lib/xaac-agent/policies/state.json").read_text())
    assert state["status"] == "confirmed"
    assert state["active_policy"]["revision"] == 1


def test_apply_preserves_previous_policy_for_rollback(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    root.mkdir()
    manager = PolicyApplicationManager(root, _profile(tmp_path))
    manager.install()
    manager.apply(manager.stage(_document(revision=1)))
    manager.confirm()
    manager.apply(manager.stage(_document(revision=2, kiosk={"allow_shutdown": True})))
    manager.rollback()
    active = json.loads((root / "var/lib/xaac-agent/policies/active/policy.json").read_text())
    assert active["revision"] == 1
    assert json.loads((root / "var/lib/xaac-agent/policies/state.json").read_text())["status"] == "rolled_back"


def test_apply_rejects_file_outside_staging(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    root.mkdir()
    manager = PolicyApplicationManager(root, _profile(tmp_path))
    manager.install()
    external = tmp_path / "policy.json"
    external.write_text(json.dumps(_document()))
    with pytest.raises(PolicyApplicationError, match="staging"):
        manager.apply(external)


def test_installer_rejects_symlink_destination(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    (root / "etc/xaac").mkdir(parents=True)
    (root / "etc/xaac/policy-application.yaml").symlink_to("/tmp/unsafe")
    with pytest.raises(PolicyApplicationError, match="enllaç simbòlic"):
        PolicyApplicationManager(root, _profile(tmp_path)).install()


def test_cli_exposes_policy_application_command() -> None:
    args = build_parser().parse_args(["configure-policy-application", "--dry-run"])
    assert args.command == "configure-policy-application"
    assert args.dry_run is True
