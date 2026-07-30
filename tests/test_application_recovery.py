from pathlib import Path
import json
import pytest

from xaac_thin_client_os.application_recovery import (
    ApplicationRecoveryError,
    ApplicationRecoveryInstaller,
    create_application_recovery_plan,
    load_application_recovery,
)
from xaac_thin_client_os.cli import build_parser, main

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path: Path) -> Path:
    path = tmp_path / ".build" / "rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "application-recovery.yaml"
    path.write_text((ROOT / "config/application-recovery.yaml").read_text().replace(old, new), encoding="utf-8")
    return path


def test_loads_complete_application_recovery_policy() -> None:
    profile = load_application_recovery(ROOT / "config/application-recovery.yaml")
    assert profile["client"]["service"] == "xaac-thin-client.service"
    assert profile["client"]["session_service"] == "xaac-kiosk-session.service"
    assert set(profile["diagnostics"]["collect"]) == {"client-status", "session-status", "client-journal", "agent-status", "policy-metadata"}


def test_manifest_is_stable(tmp_path: Path) -> None:
    manifest = create_application_recovery_plan(rootfs(tmp_path), ROOT / "config/application-recovery.yaml").manifest()
    assert manifest == {
        "schema_version": 1,
        "recovery_id": "xaac-application-recovery-1",
        "hardware_profile": "wyse3040",
        "client_service": "xaac-thin-client.service",
        "session_service": "xaac-kiosk-session.service",
        "policy_rollback": True,
        "diagnostic_count": 5,
    }


def test_installs_policy_state_runner_and_service(tmp_path: Path) -> None:
    plan = create_application_recovery_plan(rootfs(tmp_path), ROOT / "config/application-recovery.yaml")
    policy, state, runner, service = ApplicationRecoveryInstaller().install(plan)
    assert json.loads(policy.read_text())["safety"]["fail_closed"] is True
    saved = json.loads(state.read_text())
    assert saved["status"] == "idle" and saved["client_restarts"] == 0 and saved["policy_rolled_back"] is False
    assert "xaac-agent recovery application" in runner.read_text()
    unit = service.read_text()
    assert "ProtectSystem=strict" in unit and "ReadWritePaths=" in unit
    assert policy.stat().st_mode & 0o777 == 0o640
    assert state.stat().st_mode & 0o777 == 0o640
    assert runner.stat().st_mode & 0o777 == 0o750
    assert service.stat().st_mode & 0o777 == 0o644


def test_installation_is_idempotent(tmp_path: Path) -> None:
    plan = create_application_recovery_plan(rootfs(tmp_path), ROOT / "config/application-recovery.yaml")
    installer = ApplicationRecoveryInstaller()
    paths = installer.install(plan)
    before = tuple(path.read_bytes() for path in paths)
    installer.install(plan)
    assert before == tuple(path.read_bytes() for path in paths)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_application_recovery_plan(rootfs(tmp_path), ROOT / "config/application-recovery.yaml")
    paths = ApplicationRecoveryInstaller().install(plan, dry_run=True)
    assert len(paths) == 4 and not any(path.exists() for path in paths)


def test_rejects_unsafe_cleanup_overlap(tmp_path: Path) -> None:
    path = altered(tmp_path, "- /run/xaac-thin-client", "- /var/lib/xaac/device-identity.json")
    with pytest.raises(ApplicationRecoveryError, match="preservar-se i eliminar-se"):
        load_application_recovery(path)


def test_rejects_unsigned_policy_rollback(tmp_path: Path) -> None:
    path = altered(tmp_path, "require_signature_validation: true", "require_signature_validation: false")
    with pytest.raises(ApplicationRecoveryError, match="obligatori"):
        load_application_recovery(path)


def test_rejects_automatic_factory_reset(tmp_path: Path) -> None:
    path = altered(tmp_path, "automatic_factory_reset: false", "automatic_factory_reset: true")
    with pytest.raises(ApplicationRecoveryError, match="prohibit"):
        load_application_recovery(path)


def test_rejects_incomplete_diagnostics(tmp_path: Path) -> None:
    path = altered(tmp_path, "    - policy-metadata\n", "")
    with pytest.raises(ApplicationRecoveryError, match="diagnòstics incomplet"):
        load_application_recovery(path)


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    plan = create_application_recovery_plan(rootfs(tmp_path), ROOT / "config/application-recovery.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ApplicationRecoveryError, match="enllaç simbòlic"):
        ApplicationRecoveryInstaller().install(plan)


def test_cli_supports_application_recovery(tmp_path: Path) -> None:
    assert build_parser().parse_args(["configure-application-recovery", "--dry-run"]).command == "configure-application-recovery"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/application-recovery.yaml").write_text((ROOT / "config/application-recovery.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-application-recovery", "--dry-run"]) == 0
