from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.transactional_update import (
    TransactionalUpdateError,
    TransactionalUpdateInstaller,
    create_transactional_update_plan,
    load_transactional_update,
)

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path: Path) -> Path:
    path = tmp_path / ".build/rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "transaction.yaml"
    path.write_text((ROOT / "config/transactional-update.yaml").read_text().replace(old, new))
    return path


def test_loads_phase_10_2_transactional_policy() -> None:
    policy = load_transactional_update(ROOT / "config/transactional-update.yaml")
    assert policy["schema_version"] == 2
    assert policy["failure"]["automatic_rollback"] is True
    assert policy["interruption"]["rollback_on_boot"] is True
    assert policy["recovery_point"]["max_points"] == 2


def test_manifest_is_stable(tmp_path: Path) -> None:
    manifest = create_transactional_update_plan(rootfs(tmp_path), ROOT / "config/transactional-update.yaml").manifest()
    assert manifest["hardware_profile"] == "wyse3040"
    assert manifest["automatic_rollback"] is True
    assert manifest["recovery_points"] == 2


def test_installs_policy_state_recovery_service_and_tmpfiles(tmp_path: Path) -> None:
    policy, state, service, tmpfiles = TransactionalUpdateInstaller().install(
        create_transactional_update_plan(rootfs(tmp_path), ROOT / "config/transactional-update.yaml")
    )
    assert json.loads(state.read_text())["status"] == "idle"
    assert "recover-interrupted" in service.read_text()
    assert "Before=greetd.service" in service.read_text()
    assert "ProtectSystem=no" in service.read_text()
    assert "ProtectHome=yes" in service.read_text()
    assert "/var/lib/xaac-update/package-cache" in tmpfiles.read_text()
    assert policy.stat().st_mode & 0o777 == 0o640


def test_installation_is_idempotent(tmp_path: Path) -> None:
    plan = create_transactional_update_plan(rootfs(tmp_path), ROOT / "config/transactional-update.yaml")
    installer = TransactionalUpdateInstaller()
    paths = installer.install(plan)
    before = [path.read_bytes() for path in paths]
    installer.install(plan)
    assert before == [path.read_bytes() for path in paths]


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    paths = TransactionalUpdateInstaller().install(
        create_transactional_update_plan(rootfs(tmp_path), ROOT / "config/transactional-update.yaml"),
        dry_run=True,
    )
    assert len(paths) == 4 and not any(path.exists() for path in paths)


def test_rejects_optional_recovery_point(tmp_path: Path) -> None:
    with pytest.raises(TransactionalUpdateError, match="recuperació"):
        load_transactional_update(altered(tmp_path, "required: true", "required: false"))


def test_rejects_unverified_staging(tmp_path: Path) -> None:
    with pytest.raises(TransactionalUpdateError, match="Instal·lació"):
        load_transactional_update(altered(tmp_path, "require_verified_staging: true", "require_verified_staging: false"))


def test_rejects_non_fail_closed_health_check(tmp_path: Path) -> None:
    with pytest.raises(TransactionalUpdateError, match="Health-check"):
        load_transactional_update(altered(tmp_path, "fail_closed: true", "fail_closed: false"))


def test_rejects_disabled_rollback(tmp_path: Path) -> None:
    with pytest.raises(TransactionalUpdateError, match="fallada"):
        load_transactional_update(altered(tmp_path, "automatic_rollback: true", "automatic_rollback: false"))


def test_rejects_insecure_path(tmp_path: Path) -> None:
    with pytest.raises(TransactionalUpdateError, match="Ruta insegura"):
        load_transactional_update(altered(tmp_path, "/var/lib/xaac-update/recovery-points", "../recovery"))


def test_rejects_excessive_recovery_retention(tmp_path: Path) -> None:
    with pytest.raises(TransactionalUpdateError, match="Retenció"):
        load_transactional_update(altered(tmp_path, "max_points: 2", "max_points: 20"))


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    plan = create_transactional_update_plan(rootfs(tmp_path), ROOT / "config/transactional-update.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(TransactionalUpdateError, match="enllaç simbòlic"):
        TransactionalUpdateInstaller().install(plan)


def test_cli_supports_transactional_update(tmp_path: Path) -> None:
    assert build_parser().parse_args(["configure-transactional-update", "--dry-run"]).command == "configure-transactional-update"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/transactional-update.yaml").write_text((ROOT / "config/transactional-update.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-transactional-update", "--dry-run"]) == 0
