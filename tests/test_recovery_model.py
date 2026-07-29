from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.recovery_model import (
    RecoveryModelError,
    RecoveryModelInstaller,
    classify_recovery_state,
    create_recovery_model_plan,
    load_recovery_model,
)

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path: Path) -> Path:
    path = tmp_path / ".build" / "rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "recovery-model.yaml"
    path.write_text((ROOT / "config/recovery-model.yaml").read_text().replace(old, new), encoding="utf-8")
    return path


def test_loads_complete_recovery_model() -> None:
    model = load_recovery_model(ROOT / "config/recovery-model.yaml")
    assert len(model["failure_classes"]) == 4
    assert list(model["states"]) == ["healthy", "degraded", "recovering", "safe", "manual_intervention"]


def test_manifest_is_stable(tmp_path: Path) -> None:
    manifest = create_recovery_model_plan(rootfs(tmp_path), ROOT / "config/recovery-model.yaml").manifest()
    assert manifest == {"schema_version": 1, "model_id": "xaac-recovery-model-1", "hardware_profile": "wyse3040", "failure_class_count": 4, "state_count": 5, "initial_state": "healthy"}


def test_installs_policy_and_initial_state(tmp_path: Path) -> None:
    plan = create_recovery_model_plan(rootfs(tmp_path), ROOT / "config/recovery-model.yaml")
    policy, state = RecoveryModelInstaller().install(plan)
    assert json.loads(policy.read_text())["safety"]["fail_closed"] is True
    saved = json.loads(state.read_text())
    assert saved["status"] == "healthy"
    assert set(saved["counters"]) == {"application_failures", "session_failures", "update_failures", "integrity_failures"}
    assert policy.stat().st_mode & 0o777 == 0o644
    assert state.stat().st_mode & 0o777 == 0o640


def test_installation_is_idempotent(tmp_path: Path) -> None:
    plan = create_recovery_model_plan(rootfs(tmp_path), ROOT / "config/recovery-model.yaml")
    installer = RecoveryModelInstaller()
    installer.install(plan)
    before = tuple(path.read_bytes() for path in (plan.output("policy"), plan.output("state")))
    installer.install(plan)
    assert before == tuple(path.read_bytes() for path in (plan.output("policy"), plan.output("state")))


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_recovery_model_plan(rootfs(tmp_path), ROOT / "config/recovery-model.yaml")
    paths = RecoveryModelInstaller().install(plan, dry_run=True)
    assert len(paths) == 2 and not any(path.exists() for path in paths)


def test_classifies_most_severe_counter() -> None:
    model = load_recovery_model(ROOT / "config/recovery-model.yaml")
    assert classify_recovery_state(model, {}) == "healthy"
    assert classify_recovery_state(model, {"application_failures": 1}) == "degraded"
    assert classify_recovery_state(model, {"application_failures": 3, "session_failures": 5}) == "safe"
    assert classify_recovery_state(model, {"integrity_failures": 8}) == "manual_intervention"


def test_rejects_duplicate_failure_classes(tmp_path: Path) -> None:
    path = altered(tmp_path, "id: session", "id: application")
    with pytest.raises(RecoveryModelError, match="duplicats"):
        load_recovery_model(path)


def test_rejects_non_increasing_thresholds(tmp_path: Path) -> None:
    path = altered(tmp_path, "recovering: 3", "recovering: 1")
    with pytest.raises(RecoveryModelError, match="creixents"):
        load_recovery_model(path)


def test_rejects_automatic_factory_reset(tmp_path: Path) -> None:
    path = altered(tmp_path, "automatic_factory_reset: false", "automatic_factory_reset: true")
    with pytest.raises(RecoveryModelError, match="prohibit"):
        load_recovery_model(path)


def test_rejects_safe_state_without_xms_notification(tmp_path: Path) -> None:
    path = altered(tmp_path, "notify: [agent, xms]", "notify: [agent]",)
    with pytest.raises(RecoveryModelError, match="Agent i XMS"):
        load_recovery_model(path)


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    plan = create_recovery_model_plan(rootfs(tmp_path), ROOT / "config/recovery-model.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(RecoveryModelError, match="enllaç simbòlic"):
        RecoveryModelInstaller().install(plan)


def test_cli_supports_recovery_model(tmp_path: Path) -> None:
    assert build_parser().parse_args(["configure-recovery-model", "--dry-run"]).command == "configure-recovery-model"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/recovery-model.yaml").write_text((ROOT / "config/recovery-model.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-recovery-model", "--dry-run"]) == 0
