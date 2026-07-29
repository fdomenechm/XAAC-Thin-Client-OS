from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.update_rings import (
    UpdateRingsError, UpdateRingsInstaller, create_update_rings_plan, load_update_rings,
)

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path):
    path = tmp_path / ".build/rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path, old, new):
    path = tmp_path / "rings.yaml"
    path.write_text((ROOT / "config/update-rings.yaml").read_text().replace(old, new))
    return path


def test_loads_three_ordered_update_rings():
    policy = load_update_rings(ROOT / "config/update-rings.yaml")
    assert [ring["id"] for ring in policy["rings"]] == ["laboratory", "pilot", "production"]


def test_manifest_is_stable(tmp_path):
    manifest = create_update_rings_plan(rootfs(tmp_path), ROOT / "config/update-rings.yaml").manifest()
    assert manifest["rings"] == ["laboratory", "pilot", "production"]
    assert manifest["manual_promotion"] is True


def test_installs_policy_state_runner_and_service(tmp_path):
    policy, state, runner, service = UpdateRingsInstaller().install(
        create_update_rings_plan(rootfs(tmp_path), ROOT / "config/update-rings.yaml")
    )
    assert json.loads(state.read_text())["status"] == "idle"
    assert "deploy-rings" in runner.read_text()
    assert "ProtectSystem=strict" in service.read_text()
    assert policy.stat().st_mode & 0o777 == 0o640


def test_installation_is_idempotent(tmp_path):
    plan = create_update_rings_plan(rootfs(tmp_path), ROOT / "config/update-rings.yaml")
    installer = UpdateRingsInstaller()
    paths = installer.install(plan)
    before = [path.read_bytes() for path in paths]
    installer.install(plan)
    assert before == [path.read_bytes() for path in paths]


def test_dry_run_does_not_write(tmp_path):
    paths = UpdateRingsInstaller().install(create_update_rings_plan(rootfs(tmp_path), ROOT / "config/update-rings.yaml"), dry_run=True)
    assert len(paths) == 4 and not any(path.exists() for path in paths)


def test_rejects_incoherent_ring_channel(tmp_path):
    with pytest.raises(UpdateRingsError, match="Canal incoherent"):
        load_update_rings(altered(tmp_path, "channel: pilot", "channel: production"))


def test_rejects_invalid_percentage(tmp_path):
    with pytest.raises(UpdateRingsError, match="Percentatge"):
        load_update_rings(altered(tmp_path, "percentage: 10", "percentage: 0"))


def test_rejects_automatic_promotion(tmp_path):
    with pytest.raises(UpdateRingsError, match="promoció automàtica"):
        load_update_rings(altered(tmp_path, "automatic_promotion: false", "automatic_promotion: true"))


def test_rejects_missing_cancellation_control(tmp_path):
    with pytest.raises(UpdateRingsError, match="Controls"):
        load_update_rings(altered(tmp_path, "cancellation_supported: true", "cancellation_supported: false"))


def test_rejects_unstable_selection(tmp_path):
    with pytest.raises(UpdateRingsError, match="Selecció"):
        load_update_rings(altered(tmp_path, "stable_across_checks: true", "stable_across_checks: false"))


def test_rejects_symlink_destination(tmp_path):
    plan = create_update_rings_plan(rootfs(tmp_path), ROOT / "config/update-rings.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(UpdateRingsError, match="enllaç simbòlic"):
        UpdateRingsInstaller().install(plan)


def test_cli_supports_update_rings(tmp_path):
    assert build_parser().parse_args(["configure-update-rings", "--dry-run"]).command == "configure-update-rings"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/update-rings.yaml").write_text((ROOT / "config/update-rings.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-update-rings", "--dry-run"]) == 0
