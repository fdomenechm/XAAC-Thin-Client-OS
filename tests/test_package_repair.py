from pathlib import Path
import json
import pytest

from xaac_thin_client_os.package_repair import (
    PackageRepairError,
    PackageRepairInstaller,
    create_package_repair_plan,
    load_package_repair,
)
from xaac_thin_client_os.cli import build_parser, main

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path: Path) -> Path:
    path = tmp_path / ".build" / "rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "package-repair.yaml"
    path.write_text((ROOT / "config/package-repair.yaml").read_text().replace(old, new), encoding="utf-8")
    return path


def test_loads_complete_package_repair_policy() -> None:
    profile = load_package_repair(ROOT / "config/package-repair.yaml")
    assert profile["packages"]["managed"] == ["xaac-thin-client", "xaac-agent"]
    assert set(profile["final_validation"]["commands"]) == {"dpkg-audit", "apt-check", "package-files", "xaac-services"}


def test_manifest_is_stable(tmp_path: Path) -> None:
    manifest = create_package_repair_plan(rootfs(tmp_path), ROOT / "config/package-repair.yaml").manifest()
    assert manifest == {
        "schema_version": 1,
        "repair_id": "xaac-package-repair-1",
        "hardware_profile": "wyse3040",
        "managed_packages": ("xaac-thin-client", "xaac-agent"),
        "validation_count": 4,
        "max_attempts": 2,
    }


def test_installs_policy_state_runner_and_service(tmp_path: Path) -> None:
    plan = create_package_repair_plan(rootfs(tmp_path), ROOT / "config/package-repair.yaml")
    policy, state, runner, service = PackageRepairInstaller().install(plan)
    assert json.loads(policy.read_text())["verification"]["fail_closed"] is True
    saved = json.loads(state.read_text())
    assert saved["status"] == "idle" and saved["dependencies_repaired"] is False
    assert "xaac-agent recovery packages" in runner.read_text()
    assert "ProtectSystem=strict" in service.read_text()
    assert [p.stat().st_mode & 0o777 for p in (policy, state, runner, service)] == [0o640, 0o640, 0o750, 0o644]


def test_installation_is_idempotent(tmp_path: Path) -> None:
    plan = create_package_repair_plan(rootfs(tmp_path), ROOT / "config/package-repair.yaml")
    installer = PackageRepairInstaller()
    paths = installer.install(plan)
    before = tuple(path.read_bytes() for path in paths)
    installer.install(plan)
    assert before == tuple(path.read_bytes() for path in paths)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_package_repair_plan(rootfs(tmp_path), ROOT / "config/package-repair.yaml")
    paths = PackageRepairInstaller().install(plan, dry_run=True)
    assert len(paths) == 4 and not any(path.exists() for path in paths)


def test_rejects_unsigned_repository(tmp_path: Path) -> None:
    path = altered(tmp_path, "require_signed_repository: true", "require_signed_repository: false")
    with pytest.raises(PackageRepairError, match="obligatori"):
        load_package_repair(path)


def test_rejects_duplicate_managed_package(tmp_path: Path) -> None:
    path = altered(tmp_path, "  - xaac-agent", "  - xaac-thin-client")
    with pytest.raises(PackageRepairError, match="gestionats"):
        load_package_repair(path)


def test_rejects_incomplete_final_validation(tmp_path: Path) -> None:
    path = altered(tmp_path, "  - xaac-services\n", "")
    with pytest.raises(PackageRepairError, match="incompleta"):
        load_package_repair(path)


def test_rejects_automatic_factory_reset(tmp_path: Path) -> None:
    path = altered(tmp_path, "automatic_factory_reset: false", "automatic_factory_reset: true")
    with pytest.raises(PackageRepairError, match="prohibit"):
        load_package_repair(path)


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    plan = create_package_repair_plan(rootfs(tmp_path), ROOT / "config/package-repair.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(PackageRepairError, match="enllaç simbòlic"):
        PackageRepairInstaller().install(plan)


def test_cli_supports_package_repair(tmp_path: Path) -> None:
    assert build_parser().parse_args(["configure-package-repair", "--dry-run"]).command == "configure-package-repair"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/package-repair.yaml").write_text((ROOT / "config/package-repair.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-package-repair", "--dry-run"]) == 0
