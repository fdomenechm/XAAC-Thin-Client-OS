from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from xaac_thin_client_os.rustdesk_activation import (
    RustDeskActivationError,
    RustDeskActivationManager,
    create_rustdesk_activation_plan,
    load_rustdesk_activation_profile,
)


def test_profile_allows_local_and_xms_with_bounded_duration(project_root: Path) -> None:
    p = load_rustdesk_activation_profile(project_root / "config/rustdesk-activation.yaml")
    assert p["activation"]["allowed_sources"] == ["local", "xms"]
    assert p["activation"]["maximum_duration_minutes"] == 240
    assert p["activation"]["close_on_expiry"] is True


def test_installer_writes_policy_helper_timer_and_inactive_state(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_activation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-activation.yaml")
    files = RustDeskActivationManager().install(plan)
    assert len(files) == 5
    assert plan.target("helper").stat().st_mode & 0o777 == 0o750
    assert "systemctl stop rustdesk-xaac.service" in plan.target("helper").read_text()
    assert "Persistent=false" in plan.target("expiry_timer").read_text()
    assert json.loads(plan.target("state").read_text())["active"] is False


def test_activation_creates_expiring_single_use_request_without_plain_token(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_activation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-activation.yaml")
    manager = RustDeskActivationManager(); manager.install(plan)
    result = manager.activate(plan, source="xms", duration_minutes=45, token="A" * 24, now=datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc))
    request = json.loads(plan.target("request").read_text())
    assert result["expires_at"] == "2026-07-29T09:45:00+00:00"
    assert request["single_use"] is True and request["token_hash"] != "A" * 24
    assert "A" * 24 not in plan.target("request").read_text()
    assert plan.target("request").stat().st_mode & 0o777 == 0o600


def test_local_activation_uses_default_duration_and_generated_token(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_activation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-activation.yaml")
    result = RustDeskActivationManager().activate(plan, source="local", now=datetime(2026, 7, 29, tzinfo=timezone.utc))
    assert result["duration_minutes"] == 30 and len(result["token"]) >= 24


def test_rejects_invalid_source_duration_and_short_token(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_activation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-activation.yaml")
    manager = RustDeskActivationManager()
    with pytest.raises(RustDeskActivationError, match="Origen"): manager.activate(plan, source="unknown", token="A" * 24)
    with pytest.raises(RustDeskActivationError, match="Duració"): manager.activate(plan, source="xms", duration_minutes=241, token="A" * 24)
    with pytest.raises(RustDeskActivationError, match="massa curt"): manager.activate(plan, source="xms", token="short")


def test_deactivation_removes_request_and_marks_inactive(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_activation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-activation.yaml")
    manager = RustDeskActivationManager(); manager.activate(plan, source="local", token="B" * 24)
    state = manager.deactivate(plan)
    assert state["active"] is False and not plan.target("request").exists()


def test_dry_run_does_not_write(project_root: Path, tmp_path: Path) -> None:
    plan = create_rustdesk_activation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-activation.yaml")
    manager = RustDeskActivationManager()
    assert manager.install(plan, dry_run=True) == ()
    manager.activate(plan, source="xms", token="C" * 24, dry_run=True)
    assert not plan.rootfs.exists()


def test_rejects_unsafe_output_and_symlink(project_root: Path, tmp_path: Path) -> None:
    text = (project_root / "config/rustdesk-activation.yaml").read_text().replace("/run/xaac/rustdesk/activation-request.json", "../escape")
    bad = tmp_path / "bad.yaml"; bad.write_text(text)
    with pytest.raises(RustDeskActivationError, match="Ruta insegura"): load_rustdesk_activation_profile(bad)
    plan = create_rustdesk_activation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-activation.yaml")
    target = plan.target("state"); target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "outside")
    with pytest.raises(RustDeskActivationError, match="enllaç simbòlic"): RustDeskActivationManager().install(plan)


def test_cli_exposes_activation_commands() -> None:
    from xaac_thin_client_os.cli import build_parser
    parser = build_parser()
    assert parser.parse_args(["configure-rustdesk-activation", "--dry-run"]).command == "configure-rustdesk-activation"
    args = parser.parse_args(["activate-rustdesk-support", "--source", "xms", "--duration", "60", "--token", "D" * 24])
    assert args.duration == 60 and args.source == "xms"
    assert parser.parse_args(["deactivate-rustdesk-support"]).command == "deactivate-rustdesk-support"
