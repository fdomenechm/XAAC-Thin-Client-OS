from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.xms_enrollment import XmsEnrollmentError, XmsEnrollmentManager, load_xms_enrollment_profile


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "xms-enrollment.yaml"
    path.write_text(Path("config/xms-enrollment.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    identity = root / "var/lib/xaac-agent/identity/device.json"
    identity.parent.mkdir(parents=True)
    identity.write_text(json.dumps({"uuid": "12345678-1234-4234-8234-123456789abc", "hostname": "xaac-test"}))
    return root


def _manager(tmp_path: Path) -> XmsEnrollmentManager:
    return XmsEnrollmentManager(_root(tmp_path), _profile(tmp_path), now=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc))


def test_profile_requires_https(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/xms-enrollment.yaml").read_text())
    data["enrollment"]["server_url"] = "http://xms.invalid"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(XmsEnrollmentError, match="HTTPS"):
        load_xms_enrollment_profile(path)


def test_install_creates_unenrolled_state_and_manifest(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    state, request, manifest = manager.install()
    assert json.loads(state.read_text())["status"] == "unenrolled"
    assert not request.exists()
    assert "pending_approval" in json.loads(manifest.read_text())["states"]


def test_install_dry_run_does_not_write(tmp_path: Path) -> None:
    paths = _manager(tmp_path).install(dry_run=True)
    assert len(paths) == 3
    assert not paths[0].exists()


def test_request_hashes_token_and_never_persists_plaintext(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install()
    state = manager.request_enrollment("ValidEnrollmentToken-123")
    request = manager._path("request").read_text()
    assert state["status"] == "pending_approval"
    assert "ValidEnrollmentToken-123" not in request
    assert "token_sha256" in request


def test_request_rejects_short_token(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install()
    with pytest.raises(XmsEnrollmentError, match="Token"):
        manager.request_enrollment("short")


def test_approval_installs_certificates_and_clears_request(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install()
    manager.request_enrollment("ValidEnrollmentToken-123")
    state = manager.approve("-----BEGIN CERTIFICATE-----\nDEVICE\n-----END CERTIFICATE-----", "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----")
    assert state["status"] == "enrolled"
    assert manager._path("certificate").stat().st_mode & 0o777 == 0o600
    assert not manager._path("request").exists()


def test_approval_requires_pending_state(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install()
    with pytest.raises(XmsEnrollmentError, match="pendent"):
        manager.approve("-----BEGIN CERTIFICATE-----", "-----BEGIN CERTIFICATE-----")


def test_renewal_requires_enrolled_certificate(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install()
    with pytest.raises(XmsEnrollmentError, match="no està enrolat"):
        manager.request_renewal()


def test_renewal_transitions_to_pending(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install(); manager.request_enrollment("ValidEnrollmentToken-123")
    manager.approve("-----BEGIN CERTIFICATE-----\nDEVICE\n-----END CERTIFICATE-----", "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----")
    assert manager.request_renewal()["status"] == "renewal_pending"


def test_unenroll_removes_credentials(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install(); manager.request_enrollment("ValidEnrollmentToken-123")
    manager.approve("-----BEGIN CERTIFICATE-----\nDEVICE\n-----END CERTIFICATE-----", "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----")
    assert manager.unenroll()["status"] == "unenrolled"
    assert not manager._path("certificate").exists()


def test_safe_error_does_not_expose_secrets(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.install()
    state = manager.record_safe_error("  network   unavailable  ")
    assert state["status"] == "error" and state["safe"] is True
    assert state["reason"] == "network unavailable"


def test_cli_exposes_xms_enrollment_command() -> None:
    args = build_parser().parse_args(["configure-xms-enrollment", "--dry-run"])
    assert args.command == "configure-xms-enrollment"
    assert args.dry_run is True
