from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.xms_enrollment import XmsEnrollmentError, XmsEnrollmentManager, load_xms_enrollment_profile

ROOT = Path(__file__).resolve().parents[1]


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "xms-enrollment.yaml"
    path.write_text((ROOT / "config/xms-enrollment.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    target = root / "opt/xaac-agent/runtime/bin/xaac-agent-admin"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o755)
    admin = root / "usr/sbin/xaac-agent-admin"
    admin.parent.mkdir(parents=True)
    admin.symlink_to("/opt/xaac-agent/runtime/bin/xaac-agent-admin")
    config = root / "etc/xaac-agent/agent.ini"
    config.parent.mkdir(parents=True)
    config.write_text("[agent]\nenabled=false\n", encoding="utf-8")
    unit = root / "usr/lib/systemd/system/xaac-agent.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("[Service]\n", encoding="utf-8")
    return root


def test_profile_defines_agent_admin_as_the_only_enrollment_owner(tmp_path: Path) -> None:
    profile = load_xms_enrollment_profile(_profile(tmp_path))
    enrollment = profile["enrollment"]
    assert enrollment["format"] == "xaac-agent-admin"
    assert enrollment["admin_command"] == "/usr/sbin/xaac-agent-admin"
    assert enrollment["admin_target"] == "/opt/xaac-agent/runtime/bin/xaac-agent-admin"
    assert enrollment["commands"] == ["provision", "enable", "disable", "status", "unenroll"]
    assert enrollment["bootstrap_token_one_time"] is True
    assert enrollment["explicit_reenrollment"] is True


def test_profile_rejects_non_https_enrollment_contract(tmp_path: Path) -> None:
    data = yaml.safe_load((ROOT / "config/xms-enrollment.yaml").read_text(encoding="utf-8"))
    data["enrollment"]["require_https"] = False
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(XmsEnrollmentError, match="HTTPS"):
        load_xms_enrollment_profile(path)


def test_profile_rejects_secret_bearing_or_extra_admin_commands(tmp_path: Path) -> None:
    data = yaml.safe_load((ROOT / "config/xms-enrollment.yaml").read_text(encoding="utf-8"))
    data["enrollment"]["commands"].append("set-token")
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(XmsEnrollmentError, match="Superfície"):
        load_xms_enrollment_profile(path)


def test_install_writes_only_a_non_secret_contract_manifest(tmp_path: Path) -> None:
    manager = XmsEnrollmentManager(_root(tmp_path), _profile(tmp_path))
    (manifest,) = manager.install()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["contract"] == "xaac-agent-admin/v1"
    assert payload["admin_target"] == "/opt/xaac-agent/runtime/bin/xaac-agent-admin"
    assert payload["bootstrap"]["one_time"] is True
    assert payload["bootstrap"]["accepted_cli_secret_argument"] is False
    assert payload["commands"] == ["provision", "enable", "disable", "status", "unenroll"]
    assert "token_sha256" not in manifest.read_text(encoding="utf-8")
    assert "certificate" not in manifest.read_text(encoding="utf-8").lower()
    assert manifest.stat().st_mode & 0o777 == 0o640


def test_install_requires_agent_admin_package_content(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "usr/sbin/xaac-agent-admin").unlink()
    manager = XmsEnrollmentManager(root, _profile(tmp_path))
    with pytest.raises(XmsEnrollmentError, match="xaac-agent-admin"):
        manager.install()


def test_install_dry_run_does_not_require_installed_agent(tmp_path: Path) -> None:
    root = tmp_path / "empty-rootfs"
    root.mkdir()
    manager = XmsEnrollmentManager(root, _profile(tmp_path))
    paths = manager.install(dry_run=True)
    assert paths == (root / "etc/xaac/xms-enrollment-manifest.json",)
    assert not paths[0].exists()


def test_manifest_rejects_symlink(tmp_path: Path) -> None:
    root = _root(tmp_path)
    target = root / "tmp-target"
    target.write_text("do not touch", encoding="utf-8")
    manifest = root / "etc/xaac/xms-enrollment-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.symlink_to(target)
    with pytest.raises(XmsEnrollmentError, match="enllaç simbòlic"):
        XmsEnrollmentManager(root, _profile(tmp_path)).install()
    assert target.read_text(encoding="utf-8") == "do not touch"


def test_cli_exposes_xms_enrollment_contract_command() -> None:
    args = build_parser().parse_args(["configure-xms-enrollment", "--dry-run"])
    assert args.command == "configure-xms-enrollment"
    assert args.dry_run is True


def test_enrollment_rejects_admin_symlink_outside_packaged_runtime(tmp_path: Path) -> None:
    root = _root(tmp_path)
    admin = root / "usr/sbin/xaac-agent-admin"
    admin.unlink()
    admin.symlink_to("/tmp/not-authorized")
    manager = XmsEnrollmentManager(root, _profile(tmp_path))
    with pytest.raises(XmsEnrollmentError, match="runtime autoritzat"):
        manager.install()
