from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.package_rollback import (
    PackageRollbackError,
    PackageRollbackInstaller,
    create_package_rollback_plan,
    load_package_rollback,
)

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path: Path) -> Path:
    path = tmp_path / ".build/rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "rollback.yaml"
    path.write_text((ROOT / "config/package-rollback.yaml").read_text().replace(old, new))
    return path


def test_loads_phase_10_2_package_rollback_policy() -> None:
    policy = load_package_rollback(ROOT / "config/package-rollback.yaml")
    assert policy["schema_version"] == 2
    assert policy["failed_versions"]["block"] is True
    assert policy["source"]["allow_last_confirmed_transaction"] is True


def test_manifest_is_stable(tmp_path: Path) -> None:
    manifest = create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml").manifest()
    assert manifest["hardware_profile"] == "wyse3040"
    assert manifest["block_failed_versions"] is True
    assert manifest["manual_rollback"] is True


def test_installs_policy_and_state(tmp_path: Path) -> None:
    policy, state = PackageRollbackInstaller().install(
        create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml")
    )
    assert json.loads(state.read_text())["status"] == "idle"
    assert json.loads(policy.read_text())["restore"]["configuration"] is True
    assert policy.stat().st_mode & 0o777 == 0o640


def test_installation_is_idempotent(tmp_path: Path) -> None:
    plan = create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml")
    installer = PackageRollbackInstaller()
    paths = installer.install(plan)
    before = [path.read_bytes() for path in paths]
    installer.install(plan)
    assert before == [path.read_bytes() for path in paths]


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    paths = PackageRollbackInstaller().install(
        create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml"), dry_run=True
    )
    assert len(paths) == 2 and not any(path.exists() for path in paths)


def test_rejects_rollback_without_recovery_point(tmp_path: Path) -> None:
    with pytest.raises(PackageRollbackError, match="Origen"):
        load_package_rollback(altered(tmp_path, "require_recovery_point: true", "require_recovery_point: false"))


def test_rejects_missing_configuration_restore(tmp_path: Path) -> None:
    with pytest.raises(PackageRollbackError, match="Restauració"):
        load_package_rollback(altered(tmp_path, "configuration: true", "configuration: false"))


def test_rejects_non_fail_closed_validation(tmp_path: Path) -> None:
    with pytest.raises(PackageRollbackError, match="Validació"):
        load_package_rollback(altered(tmp_path, "fail_closed: true", "fail_closed: false"))


def test_rejects_unblocked_failed_version(tmp_path: Path) -> None:
    with pytest.raises(PackageRollbackError, match="Bloqueig"):
        load_package_rollback(altered(tmp_path, "block: true", "block: false"))


def test_rejects_insecure_registry_path(tmp_path: Path) -> None:
    with pytest.raises(PackageRollbackError, match="Ruta insegura"):
        load_package_rollback(altered(tmp_path, "/var/lib/xaac-update/blocked-versions.json", "../blocked.json"))


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    plan = create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(PackageRollbackError, match="enllaç simbòlic"):
        PackageRollbackInstaller().install(plan)


def test_cli_supports_package_rollback(tmp_path: Path) -> None:
    assert build_parser().parse_args(["configure-package-rollback", "--dry-run"]).command == "configure-package-rollback"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/package-rollback.yaml").write_text((ROOT / "config/package-rollback.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-package-rollback", "--dry-run"]) == 0
