from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from xaac_thin_client_os.rustdesk_session_audit import (
    RustDeskSessionAuditError,
    RustDeskSessionAuditManager,
    create_rustdesk_session_audit_plan,
    load_rustdesk_session_audit_profile,
)


def test_profile_is_append_only_and_requires_complete_session_identity(project_root: Path) -> None:
    profile = load_rustdesk_session_audit_profile(project_root / "config/rustdesk-session-audit.yaml")
    assert profile["audit"]["append_only"] is True
    assert profile["audit"]["required_fields"] == ["session_id", "operator", "device_id", "reason", "started_at"]
    assert profile["audit"]["duration_unit"] == "seconds"


def test_install_creates_idle_agent_state(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_session_audit_plan(tmp_path / "rootfs", project_root / "config/rustdesk-session-audit.yaml")
    files = RustDeskSessionAuditManager().install(plan)
    assert files == (plan.target("state"),)
    assert json.loads(plan.target("state").read_text())["status"] == "idle"
    assert plan.target("state").stat().st_mode & 0o777 == 0o640


def test_start_records_operator_device_reason_and_active_state(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_session_audit_plan(tmp_path / "rootfs", project_root / "config/rustdesk-session-audit.yaml")
    state = RustDeskSessionAuditManager().start(plan, session_id="s-1", operator="operator@example", device_id="device-1", reason="Diagnòstic", now=datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc))
    assert state["status"] == "active"
    active = json.loads(plan.target("active_session").read_text())
    assert active["operator"] == "operator@example" and active["device_id"] == "device-1" and active["reason"] == "Diagnòstic"
    assert plan.target("active_session").stat().st_mode & 0o777 == 0o600
    assert "session-started" in plan.target("journal").read_text()


def test_end_records_duration_and_final_status(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_session_audit_plan(tmp_path / "rootfs", project_root / "config/rustdesk-session-audit.yaml")
    manager = RustDeskSessionAuditManager()
    manager.start(plan, session_id="s-2", operator="op", device_id="dev", reason="Manteniment", started_at="2026-07-29T10:00:00+00:00")
    state = manager.end(plan, session_id="s-2", status="completed", ended_at="2026-07-29T10:05:30+00:00")
    assert state["last_duration_seconds"] == 330 and state["status"] == "idle"
    assert not plan.target("active_session").exists()
    events = [json.loads(line) for line in plan.target("journal").read_text().splitlines()]
    assert events[-1]["duration_seconds"] == 330 and events[-1]["status"] == "completed"


def test_rejects_duplicate_start_unknown_session_and_invalid_status(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_session_audit_plan(tmp_path / "rootfs", project_root / "config/rustdesk-session-audit.yaml")
    manager = RustDeskSessionAuditManager()
    manager.start(plan, session_id="s", operator="op", device_id="dev", reason="test", started_at="2026-07-29T10:00:00+00:00")
    with pytest.raises(RustDeskSessionAuditError, match="Ja existeix"):
        manager.start(plan, session_id="other", operator="op", device_id="dev", reason="test")
    with pytest.raises(RustDeskSessionAuditError, match="no coincideix"):
        manager.end(plan, session_id="other", status="completed")
    with pytest.raises(RustDeskSessionAuditError, match="invàlid"):
        manager.end(plan, session_id="s", status="unknown")


def test_rejects_incomplete_values_bad_dates_and_negative_duration(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_session_audit_plan(tmp_path / "rootfs", project_root / "config/rustdesk-session-audit.yaml")
    manager = RustDeskSessionAuditManager()
    with pytest.raises(RustDeskSessionAuditError, match="incomplet"):
        manager.start(plan, session_id="", operator="op", device_id="dev", reason="test")
    with pytest.raises(RustDeskSessionAuditError, match="zona horària"):
        manager.start(plan, session_id="s", operator="op", device_id="dev", reason="test", started_at="2026-07-29T10:00:00")
    manager.start(plan, session_id="s", operator="op", device_id="dev", reason="test", started_at="2026-07-29T10:00:00+00:00")
    with pytest.raises(RustDeskSessionAuditError, match="anterior"):
        manager.end(plan, session_id="s", status="failed", ended_at="2026-07-29T09:59:59+00:00")


def test_dry_run_and_symlink_protection(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_session_audit_plan(tmp_path / "rootfs", project_root / "config/rustdesk-session-audit.yaml")
    manager = RustDeskSessionAuditManager()
    assert manager.install(plan, dry_run=True) == ()
    manager.start(plan, session_id="s", operator="op", device_id="dev", reason="test", dry_run=True)
    assert not plan.rootfs.exists()
    target = plan.target("state"); target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "outside")
    with pytest.raises(RustDeskSessionAuditError, match="enllaç simbòlic"):
        manager.install(plan)


def test_rejects_unsafe_output_and_cli_exposes_audit_commands(project_root: Path, tmp_path: Path) -> None:
    text = (project_root / "config/rustdesk-session-audit.yaml").read_text().replace("/run/xaac/rustdesk/audit-active-session.json", "../escape")
    bad = tmp_path / "bad.yaml"; bad.write_text(text)
    with pytest.raises(RustDeskSessionAuditError, match="Ruta insegura"):
        load_rustdesk_session_audit_profile(bad)
    from xaac_thin_client_os.cli import build_parser
    parser = build_parser()
    assert parser.parse_args(["configure-rustdesk-audit", "--dry-run"]).command == "configure-rustdesk-audit"
    assert parser.parse_args(["start-rustdesk-audit", "--session-id", "s", "--operator", "op", "--device-id", "d", "--reason", "r"]).source == "xms"
    assert parser.parse_args(["end-rustdesk-audit", "--session-id", "s", "--status", "completed"]).status == "completed"
