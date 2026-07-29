from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaac_thin_client_os.security_policy import (
    SecurityPolicyError,
    SecurityPolicyInstaller,
    create_security_policy_plan,
    load_security_policy,
)


def test_profile_is_complete_and_cross_referenced(project_root: Path) -> None:
    profile = load_security_policy(project_root / "config/security-policy.yaml")
    assert profile["policy_id"] == "xaac-thin-client-os-base"
    assert len(profile["assets"]) == 5
    assert len(profile["actors"]) == 5
    assert len(profile["attack_surfaces"]) == 5
    assert len(profile["threats"]) == 5
    assert len(profile["controls"]) == 11
    assert len(profile["accepted_risks"]) == 2


def test_plan_manifest_is_deterministic(tmp_path: Path, project_root: Path) -> None:
    plan = create_security_policy_plan(tmp_path / "build/rootfs", project_root / "config/security-policy.yaml")
    manifest = plan.to_manifest()
    assert manifest["threat_count"] == 5
    assert manifest["accepted_risk_count"] == 2
    assert manifest["outputs"]["policy"].endswith("base-policy.json")


def test_install_is_atomic_idempotent_and_sets_permissions(tmp_path: Path, project_root: Path) -> None:
    plan = create_security_policy_plan(tmp_path / "build/rootfs", project_root / "config/security-policy.yaml")
    installer = SecurityPolicyInstaller()
    assert installer.install(plan, dry_run=True)
    first = installer.install(plan)
    before = [path.read_bytes() for path in first]
    second = installer.install(plan)
    assert [path.read_bytes() for path in second] == before
    assert [path.stat().st_mode & 0o777 for path in first] == [0o640, 0o644, 0o640]
    assert not list(plan.rootfs.rglob("*.tmp"))
    state = json.loads(first[2].read_text(encoding="utf-8"))
    assert state["status"] == "installed"


def test_policy_output_excludes_risk_details(tmp_path: Path, project_root: Path) -> None:
    plan = create_security_policy_plan(tmp_path / "build/rootfs", project_root / "config/security-policy.yaml")
    policy, threat_model, _ = SecurityPolicyInstaller().install(plan)
    assert "threats" not in json.loads(policy.read_text(encoding="utf-8"))
    assert len(json.loads(threat_model.read_text(encoding="utf-8"))["accepted_risks"]) == 2


def test_unsafe_root_and_symlink_are_rejected(tmp_path: Path, project_root: Path) -> None:
    profile = project_root / "config/security-policy.yaml"
    with pytest.raises(SecurityPolicyError, match="Rootfs insegur"):
        create_security_policy_plan(Path("/"), profile)
    plan = create_security_policy_plan(tmp_path / "build/rootfs", profile)
    target = plan.rootfs / "etc/xaac/security/base-policy.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(SecurityPolicyError, match="enllaç simbòlic"):
        SecurityPolicyInstaller().install(plan)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("status: baseline", "status: draft", "Versió o estat"),
        ("criticality: critical", "criticality: urgent", "Criticitat"),
        ("trust: untrusted", "trust: unknown", "confiança"),
        ("type: preventive", "type: advisory", "Tipus de control"),
        ("controls: [C01, C02]", "controls: [C99]", "Referència desconeguda"),
        ("threat: T03", "threat: T99", "Risc acceptat"),
        ("policy: /etc/xaac/security/base-policy.json", "policy: ../outside", "absolutes"),
    ],
)
def test_invalid_profiles_are_rejected(tmp_path: Path, project_root: Path, old: str, new: str, message: str) -> None:
    source = (project_root / "config/security-policy.yaml").read_text(encoding="utf-8")
    assert old in source
    path = tmp_path / "policy.yaml"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(SecurityPolicyError, match=message):
        load_security_policy(path)


def test_cli_exposes_security_policy_command() -> None:
    from xaac_thin_client_os.cli import build_parser

    args = build_parser().parse_args(["configure-security-policy", "--dry-run"])
    assert args.command == "configure-security-policy"
    assert args.dry_run
