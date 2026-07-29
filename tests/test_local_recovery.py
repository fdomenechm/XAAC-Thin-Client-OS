from pathlib import Path
import json
import pytest

from xaac_thin_client_os.local_recovery import (
    LocalRecoveryError, LocalRecoveryInstaller, create_local_recovery_plan, load_local_recovery,
)
from xaac_thin_client_os.cli import build_parser, main

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path: Path) -> Path:
    path = tmp_path / ".build" / "rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "local-recovery.yaml"
    path.write_text((ROOT / "config/local-recovery.yaml").read_text().replace(old, new), encoding="utf-8")
    return path


def test_loads_complete_local_recovery_policy() -> None:
    profile = load_local_recovery(ROOT / "config/local-recovery.yaml")
    assert profile["environment"]["network_default"] == "disabled"
    assert set(profile["menu"]["actions"]) == {"diagnostics", "restart-client", "restart-session", "repair-packages", "rollback-policy", "reboot", "poweroff"}


def test_manifest_is_stable(tmp_path: Path) -> None:
    assert create_local_recovery_plan(rootfs(tmp_path), ROOT / "config/local-recovery.yaml").manifest() == {
        "schema_version": 1, "recovery_id": "xaac-local-recovery-1", "hardware_profile": "wyse3040",
        "action_count": 7, "network_default": "disabled", "max_authentication_attempts": 3,
    }


def test_installs_complete_recovery_environment(tmp_path: Path) -> None:
    plan = create_local_recovery_plan(rootfs(tmp_path), ROOT / "config/local-recovery.yaml")
    policy, state, runner, service, target, grub = LocalRecoveryInstaller().install(plan)
    assert json.loads(policy.read_text())["authentication"]["required"] is True
    assert json.loads(state.read_text())["status"] == "inactive"
    assert "recovery local-menu" in runner.read_text()
    assert "ProtectSystem=strict" in service.read_text()
    assert "AllowIsolate=yes" in target.read_text()
    assert "systemd.unit=xaac-recovery.target" in grub.read_text()
    assert [p.stat().st_mode & 0o777 for p in (policy, state, runner, service, target, grub)] == [0o640, 0o640, 0o750, 0o644, 0o644, 0o750]


def test_installation_is_idempotent(tmp_path: Path) -> None:
    plan = create_local_recovery_plan(rootfs(tmp_path), ROOT / "config/local-recovery.yaml")
    installer = LocalRecoveryInstaller()
    paths = installer.install(plan)
    before = tuple(path.read_bytes() for path in paths)
    installer.install(plan)
    assert before == tuple(path.read_bytes() for path in paths)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_local_recovery_plan(rootfs(tmp_path), ROOT / "config/local-recovery.yaml")
    paths = LocalRecoveryInstaller().install(plan, dry_run=True)
    assert len(paths) == 6 and not any(path.exists() for path in paths)


def test_rejects_recovery_without_authentication(tmp_path: Path) -> None:
    with pytest.raises(LocalRecoveryError, match="autenticació"):
        load_local_recovery(altered(tmp_path, "required: true", "required: false"))


def test_rejects_network_enabled_by_default(tmp_path: Path) -> None:
    with pytest.raises(LocalRecoveryError, match="xarxa"):
        load_local_recovery(altered(tmp_path, "network_default: disabled", "network_default: enabled"))


def test_rejects_incomplete_menu(tmp_path: Path) -> None:
    with pytest.raises(LocalRecoveryError, match="Menú"):
        load_local_recovery(altered(tmp_path, "    - poweroff\n", ""))


def test_rejects_automatic_factory_reset(tmp_path: Path) -> None:
    with pytest.raises(LocalRecoveryError, match="prohibit"):
        load_local_recovery(altered(tmp_path, "automatic_factory_reset: false", "automatic_factory_reset: true"))


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    plan = create_local_recovery_plan(rootfs(tmp_path), ROOT / "config/local-recovery.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(LocalRecoveryError, match="enllaç simbòlic"):
        LocalRecoveryInstaller().install(plan)


def test_cli_supports_local_recovery(tmp_path: Path) -> None:
    assert build_parser().parse_args(["configure-local-recovery", "--dry-run"]).command == "configure-local-recovery"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/local-recovery.yaml").write_text((ROOT / "config/local-recovery.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-local-recovery", "--dry-run"]) == 0
