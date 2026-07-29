import json
from pathlib import Path

import pytest

from xaac_thin_client_os.cli import main
from xaac_thin_client_os.rustdesk_kiosk_validation import (
    RustDeskKioskValidationError,
    RustDeskKioskValidationManager,
    create_rustdesk_kiosk_validation_plan,
    load_rustdesk_kiosk_validation_profile,
)


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def evidence() -> dict:
    return {
        "capture": {"available": True, "mechanism": "pipewire"},
        "input": {"keyboard": True, "pointer": True, "mechanism": "uinput"},
        "multimonitor": {"count": 2, "dynamic_reconfiguration": True},
        "backends": {"wayland": True, "x11": True},
        "lockdown": {
            "attempted_actions": ["launch-terminal", "switch-application", "close-kiosk", "open-system-menu"],
            "blocked_actions": ["launch-terminal", "switch-application", "close-kiosk", "open-system-menu"],
        },
        "performance": {
            "startup_seconds": 4.2,
            "idle_rss_mib": 96,
            "active_cpu_percent": 22.5,
            "input_latency_ms": 54,
        },
    }


def test_profile_loads(project_root: Path) -> None:
    profile = load_rustdesk_kiosk_validation_profile(project_root / "config/rustdesk-kiosk-validation.yaml")
    assert profile["validation"]["display_backends"] == ["wayland", "x11"]


def test_rejects_unsafe_output(tmp_path: Path, project_root: Path) -> None:
    text = (project_root / "config/rustdesk-kiosk-validation.yaml").read_text()
    profile = tmp_path / "invalid.yaml"
    profile.write_text(text.replace("/var/lib/xaac-agent/rustdesk/kiosk-validation-state.json", "../state.json"))
    with pytest.raises(RustDeskKioskValidationError, match="Ruta insegura"):
        load_rustdesk_kiosk_validation_profile(profile)


def test_install_writes_policy_checklist_and_state(tmp_path: Path, project_root: Path) -> None:
    plan = create_rustdesk_kiosk_validation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-kiosk-validation.yaml")
    paths = RustDeskKioskValidationManager().install(plan)
    assert len(paths) == 3
    assert json.loads(plan.target("state").read_text())["status"] == "not-run"
    assert plan.target("state").stat().st_mode & 0o777 == 0o640


def test_validation_passes_and_persists_report(tmp_path: Path, project_root: Path, evidence: dict) -> None:
    plan = create_rustdesk_kiosk_validation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-kiosk-validation.yaml")
    report = RustDeskKioskValidationManager().validate(plan, evidence)
    assert report["passed"] is True
    assert json.loads(plan.target("report").read_text())["status"] == "passed"


def test_validation_reports_capture_and_performance_failures(tmp_path: Path, project_root: Path, evidence: dict) -> None:
    plan = create_rustdesk_kiosk_validation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-kiosk-validation.yaml")
    evidence["capture"]["available"] = False
    evidence["performance"]["input_latency_ms"] = 500
    report = RustDeskKioskValidationManager().validate(plan, evidence)
    assert report["passed"] is False
    assert "capture" in report["failures"]
    assert "performance:input_latency_ms" in report["failures"]


def test_validation_requires_both_backends(tmp_path: Path, project_root: Path, evidence: dict) -> None:
    plan = create_rustdesk_kiosk_validation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-kiosk-validation.yaml")
    evidence["backends"]["x11"] = False
    assert "x11" in RustDeskKioskValidationManager().validate(plan, evidence)["failures"]


def test_symlink_state_is_rejected(tmp_path: Path, project_root: Path) -> None:
    plan = create_rustdesk_kiosk_validation_plan(tmp_path / "rootfs", project_root / "config/rustdesk-kiosk-validation.yaml")
    target = plan.target("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(RustDeskKioskValidationError, match="enllaç simbòlic"):
        RustDeskKioskValidationManager().install(plan)


def test_cli_configure_and_validate_dry_run(tmp_path: Path, project_root: Path, evidence: dict) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    assert main(["--root", str(project_root), "configure-rustdesk-kiosk-validation", "--dry-run"]) == 0
    assert main(["--root", str(project_root), "validate-rustdesk-kiosk", "--evidence", str(evidence_path), "--dry-run"]) == 0
