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


def rootfs(tmp_path):
    path = tmp_path / ".build/rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path, old, new):
    path = tmp_path / "rollback.yaml"
    path.write_text((ROOT / "config/package-rollback.yaml").read_text().replace(old, new))
    return path


def test_loads_package_rollback_policy():
    policy = load_package_rollback(ROOT / "config/package-rollback.yaml")
    assert policy["failed_versions"]["block"] is True


def test_manifest_is_stable(tmp_path):
    manifest = create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml").manifest()
    assert manifest["hardware_profile"] == "wyse3040"
    assert manifest["block_failed_versions"] is True


def test_installs_policy_state_runner_and_service(tmp_path):
    policy, state, runner, service = PackageRollbackInstaller().install(
        create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml")
    )
    assert json.loads(state.read_text())["status"] == "idle"
    assert "rollback-packages" in runner.read_text()
    assert "ProtectSystem=strict" in service.read_text()
    assert policy.stat().st_mode & 0o777 == 0o640


def test_installation_is_idempotent(tmp_path):
    plan = create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml")
    installer = PackageRollbackInstaller()
    paths = installer.install(plan)
    before = [path.read_bytes() for path in paths]
    installer.install(plan)
    assert before == [path.read_bytes() for path in paths]


def test_dry_run_does_not_write(tmp_path):
    paths = PackageRollbackInstaller().install(
        create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml"), dry_run=True
    )
    assert len(paths) == 4 and not any(path.exists() for path in paths)


def test_rejects_rollback_without_failed_transaction(tmp_path):
    with pytest.raises(PackageRollbackError, match="Origen"):
        load_package_rollback(altered(tmp_path, "require_failed_transaction: true", "require_failed_transaction: false"))


def test_rejects_missing_configuration_restore(tmp_path):
    with pytest.raises(PackageRollbackError, match="Restauració"):
        load_package_rollback(altered(tmp_path, "configuration: true", "configuration: false"))


def test_rejects_non_fail_closed_validation(tmp_path):
    with pytest.raises(PackageRollbackError, match="Validació"):
        load_package_rollback(altered(tmp_path, "fail_closed: true", "fail_closed: false"))


def test_rejects_unblocked_failed_version(tmp_path):
    with pytest.raises(PackageRollbackError, match="Bloqueig"):
        load_package_rollback(altered(tmp_path, "block: true", "block: false"))


def test_rejects_insecure_registry_path(tmp_path):
    with pytest.raises(PackageRollbackError, match="Ruta insegura"):
        load_package_rollback(altered(tmp_path, "/var/lib/xaac-update/blocked-versions.json", "../blocked.json"))


def test_rejects_symlink_destination(tmp_path):
    plan = create_package_rollback_plan(rootfs(tmp_path), ROOT / "config/package-rollback.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(PackageRollbackError, match="enllaç simbòlic"):
        PackageRollbackInstaller().install(plan)


def test_cli_supports_package_rollback(tmp_path):
    assert build_parser().parse_args(["configure-package-rollback", "--dry-run"]).command == "configure-package-rollback"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/package-rollback.yaml").write_text((ROOT / "config/package-rollback.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-package-rollback", "--dry-run"]) == 0
