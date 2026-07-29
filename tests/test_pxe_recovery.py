from pathlib import Path
import json
import pytest

from xaac_thin_client_os.pxe_recovery import (
    PxeRecoveryError,
    PxeRecoveryInstaller,
    create_pxe_recovery_plan,
    load_pxe_recovery,
)
from xaac_thin_client_os.cli import build_parser, main

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path):
    path = tmp_path / ".build/rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path, old, new):
    path = tmp_path / "pxe-recovery.yaml"
    path.write_text((ROOT / "config/pxe-recovery.yaml").read_text().replace(old, new))
    return path


def test_loads_pxe_recovery():
    profile = load_pxe_recovery(ROOT / "config/pxe-recovery.yaml")
    assert profile["network_boot"]["protocol"] == "https"
    assert profile["authorization"]["require_xms_order"] is True


def test_manifest_is_stable(tmp_path):
    manifest = create_pxe_recovery_plan(rootfs(tmp_path), ROOT / "config/pxe-recovery.yaml").manifest()
    assert manifest == {
        "schema_version": 1,
        "recovery_id": "xaac-pxe-recovery-1",
        "transport": "https",
        "loader": "ipxe",
        "xms_order_required": True,
        "local_confirmation_required": True,
        "signature_required": True,
    }


def test_installs_pxe_recovery_assets(tmp_path):
    paths = PxeRecoveryInstaller().install(create_pxe_recovery_plan(rootfs(tmp_path), ROOT / "config/pxe-recovery.yaml"))
    policy, state, ipxe, service, runner, network = paths
    assert json.loads(policy.read_text())["authorization"]["single_use_order"] is True
    assert json.loads(state.read_text())["status"] == "idle"
    assert "https://" in ipxe.read_text() and "boot || exit" in ipxe.read_text()
    assert "ConditionACPower=true" in service.read_text()
    assert "--require-xms-order" in runner.read_text()
    assert "Name=en*" in network.read_text()
    assert [path.stat().st_mode & 0o777 for path in paths] == [0o640, 0o640, 0o644, 0o644, 0o750, 0o644]


def test_idempotent(tmp_path):
    plan = create_pxe_recovery_plan(rootfs(tmp_path), ROOT / "config/pxe-recovery.yaml")
    installer = PxeRecoveryInstaller()
    paths = installer.install(plan)
    before = [path.read_bytes() for path in paths]
    installer.install(plan)
    assert before == [path.read_bytes() for path in paths]


def test_dry_run(tmp_path):
    paths = PxeRecoveryInstaller().install(create_pxe_recovery_plan(rootfs(tmp_path), ROOT / "config/pxe-recovery.yaml"), dry_run=True)
    assert len(paths) == 6 and not any(path.exists() for path in paths)


def test_rejects_plain_http(tmp_path):
    with pytest.raises(PxeRecoveryError, match="URL HTTPS"):
        load_pxe_recovery(altered(tmp_path, "https://xms.example.invalid/recovery/wyse3040/vmlinuz", "http://xms.example.invalid/recovery/wyse3040/vmlinuz"))


def test_rejects_missing_xms_order(tmp_path):
    with pytest.raises(PxeRecoveryError, match="Autorització XMS"):
        load_pxe_recovery(altered(tmp_path, "require_xms_order: true", "require_xms_order: false"))


def test_rejects_reusable_order(tmp_path):
    with pytest.raises(PxeRecoveryError, match="Autorització XMS"):
        load_pxe_recovery(altered(tmp_path, "single_use_order: true", "single_use_order: false"))


def test_rejects_missing_local_confirmation(tmp_path):
    with pytest.raises(PxeRecoveryError, match="Confirmació local"):
        load_pxe_recovery(altered(tmp_path, "require_local_confirmation: true", "require_local_confirmation: false"))


def test_rejects_symlink(tmp_path):
    plan = create_pxe_recovery_plan(rootfs(tmp_path), ROOT / "config/pxe-recovery.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(PxeRecoveryError, match="enllaç simbòlic"):
        PxeRecoveryInstaller().install(plan)


def test_cli(tmp_path):
    assert build_parser().parse_args(["configure-pxe-recovery", "--dry-run"]).command == "configure-pxe-recovery"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/pxe-recovery.yaml").write_text((ROOT / "config/pxe-recovery.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-pxe-recovery", "--dry-run"]) == 0
