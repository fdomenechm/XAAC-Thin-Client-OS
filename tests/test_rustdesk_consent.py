from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from xaac_thin_client_os.rustdesk_consent import (
    RustDeskConsentError,
    RustDeskConsentManager,
    create_rustdesk_consent_plan,
    load_rustdesk_consent_profile,
)


def test_profile_requires_consent_by_default_and_restricts_unattended(project_root: Path) -> None:
    profile = load_rustdesk_consent_profile(project_root / "config/rustdesk-consent.yaml")
    assert profile["consent"]["default_mode"] == "required"
    assert profile["consent"]["unattended"]["allowed_sources"] == ["xms"]
    assert profile["consent"]["allow_user_cancel"] is True


def test_install_writes_policy_notifier_and_idle_state(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_consent_plan(tmp_path / "rootfs", project_root / "config/rustdesk-consent.yaml")
    files = RustDeskConsentManager().install(plan)
    assert len(files) == 3
    assert plan.target("notifier").stat().st_mode & 0o777 == 0o750
    assert json.loads(plan.target("state").read_text())["status"] == "idle"
    assert json.loads(plan.target("policy").read_text())["notification"]["channel"] == "kiosk-overlay"


def test_required_consent_creates_pending_request_and_audit(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_consent_plan(tmp_path / "rootfs", project_root / "config/rustdesk-consent.yaml")
    result = RustDeskConsentManager().request(plan, session_id="session-1", source="xms", operator="support@example", reason="Diagnòstic", expires_at="2026-07-29T12:00:00+00:00", now=datetime(2026, 7, 29, 11, 0, tzinfo=timezone.utc))
    assert result["status"] == "pending"
    request = json.loads(plan.target("request").read_text())
    assert request["operator"] == "support@example" and request["reason"] == "Diagnòstic"
    assert plan.target("request").stat().st_mode & 0o777 == 0o600
    assert "consent-requested" in plan.target("audit_log").read_text()


def test_authorized_unattended_requires_all_policy_guards(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_consent_plan(tmp_path / "rootfs", project_root / "config/rustdesk-consent.yaml")
    manager = RustDeskConsentManager()
    kwargs = dict(session_id="session-2", source="xms", operator="admin", reason="Manteniment", expires_at="2026-07-29T12:00:00+00:00", mode="authorized-unattended")
    with pytest.raises(RustDeskConsentError, match="no autoritzat"):
        manager.request(plan, **kwargs)
    result = manager.request(plan, managed_device=True, policy_authorized=True, **kwargs)
    assert result["status"] == "approved" and result["decision"] == "policy-authorized"


def test_unattended_is_never_allowed_from_local_source(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_consent_plan(tmp_path / "rootfs", project_root / "config/rustdesk-consent.yaml")
    with pytest.raises(RustDeskConsentError, match="no autoritzat"):
        RustDeskConsentManager().request(plan, session_id="s", source="local", operator="admin", reason="test", expires_at="later", mode="authorized-unattended", managed_device=True, policy_authorized=True)


def test_decision_approves_denies_or_cancels_and_removes_request(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_consent_plan(tmp_path / "rootfs", project_root / "config/rustdesk-consent.yaml")
    manager = RustDeskConsentManager()
    manager.request(plan, session_id="session-3", source="xms", operator="admin", reason="test", expires_at="later")
    result = manager.decide(plan, decision="cancel", session_id="session-3")
    assert result["status"] == "cancelled" and not plan.target("request").exists()
    assert '"decision": "cancel"' in plan.target("audit_log").read_text()


def test_rejects_incomplete_request_invalid_decision_and_unsafe_output(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_consent_plan(tmp_path / "rootfs", project_root / "config/rustdesk-consent.yaml")
    manager = RustDeskConsentManager()
    with pytest.raises(RustDeskConsentError, match="incompleta"):
        manager.request(plan, session_id="", source="xms", operator="admin", reason="test", expires_at="later")
    with pytest.raises(RustDeskConsentError, match="invàlida"):
        manager.decide(plan, decision="maybe", session_id="s")
    text = (project_root / "config/rustdesk-consent.yaml").read_text().replace("/run/xaac/rustdesk/consent-request.json", "../escape")
    bad = tmp_path / "bad.yaml"; bad.write_text(text)
    with pytest.raises(RustDeskConsentError, match="Ruta insegura"):
        load_rustdesk_consent_profile(bad)


def test_dry_run_and_symlink_protection(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_consent_plan(tmp_path / "rootfs", project_root / "config/rustdesk-consent.yaml")
    manager = RustDeskConsentManager()
    assert manager.install(plan, dry_run=True) == ()
    manager.request(plan, session_id="s", source="xms", operator="admin", reason="test", expires_at="later", dry_run=True)
    assert not plan.rootfs.exists()
    target = plan.target("state"); target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "outside")
    with pytest.raises(RustDeskConsentError, match="enllaç simbòlic"):
        manager.install(plan)


def test_cli_exposes_consent_commands() -> None:
    from xaac_thin_client_os.cli import build_parser
    parser = build_parser()
    assert parser.parse_args(["configure-rustdesk-consent", "--dry-run"]).command == "configure-rustdesk-consent"
    args = parser.parse_args(["request-rustdesk-consent", "--session-id", "s1", "--operator", "op", "--reason", "r", "--expires-at", "later"])
    assert args.mode == "required"
    args = parser.parse_args(["decide-rustdesk-consent", "--session-id", "s1", "--decision", "approve"])
    assert args.decision == "approve"
