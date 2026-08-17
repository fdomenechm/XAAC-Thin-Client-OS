from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.update_model import (
    UpdateModelError,
    UpdateModelInstaller,
    create_update_model_plan,
    load_update_model,
)

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path: Path) -> Path:
    path = tmp_path / ".build" / "rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "update-model.yaml"
    path.write_text((ROOT / "config/update-model.yaml").read_text().replace(old, new), encoding="utf-8")
    return path


def test_loads_complete_update_model() -> None:
    model = load_update_model(ROOT / "config/update-model.yaml")
    assert len(model["components"]) == 3
    assert [channel["id"] for channel in model["channels"]] == ["laboratory", "pilot", "production"]
    assert model["states"]["initial"] == "idle"


def test_manifest_is_stable(tmp_path: Path) -> None:
    manifest = create_update_model_plan(rootfs(tmp_path), ROOT / "config/update-model.yaml").manifest()
    assert manifest == {
        "schema_version": 1,
        "model_id": "xaac-update-model-1",
        "hardware_profile": "wyse3040",
        "component_count": 3,
        "channel_count": 3,
        "initial_state": "idle",
    }


def test_installs_policy_and_initial_state_with_safe_permissions(tmp_path: Path) -> None:
    plan = create_update_model_plan(rootfs(tmp_path), ROOT / "config/update-model.yaml")
    policy, state = UpdateModelInstaller().install(plan)
    assert json.loads(policy.read_text())["version_policy"]["format"] == "semver"
    assert json.loads(state.read_text())["status"] == "idle"
    assert policy.stat().st_mode & 0o777 == 0o644
    assert state.stat().st_mode & 0o777 == 0o640


def test_installation_is_idempotent(tmp_path: Path) -> None:
    plan = create_update_model_plan(rootfs(tmp_path), ROOT / "config/update-model.yaml")
    installer = UpdateModelInstaller()
    installer.install(plan)
    before = tuple(path.read_bytes() for path in (plan.output("policy"), plan.output("state")))
    installer.install(plan)
    assert before == tuple(path.read_bytes() for path in (plan.output("policy"), plan.output("state")))


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_update_model_plan(rootfs(tmp_path), ROOT / "config/update-model.yaml")
    paths = UpdateModelInstaller().install(plan, dry_run=True)
    assert len(paths) == 2
    assert not any(path.exists() for path in paths)


def test_rejects_duplicate_components(tmp_path: Path) -> None:
    path = altered(tmp_path, "id: xaac-agent", "id: xaac-thin-client")
    with pytest.raises(UpdateModelError, match="duplicats"):
        load_update_model(path)


def test_rejects_unknown_promotion_channel(tmp_path: Path) -> None:
    path = altered(tmp_path, "promotion_target: pilot", "promotion_target: unknown")
    with pytest.raises(UpdateModelError, match="inexistent"):
        load_update_model(path)


def test_rejects_invalid_maintenance_time(tmp_path: Path) -> None:
    path = altered(tmp_path, 'start: 02:00', 'start: 25:00')
    with pytest.raises(UpdateModelError, match="Hora"):
        load_update_model(path)


def test_rejects_unknown_atomic_component(tmp_path: Path) -> None:
    path = altered(tmp_path, "  - - xaac-thin-client\n    - xaac-agent", "  - - xaac-thin-client\n    - missing")
    with pytest.raises(UpdateModelError, match="atòmic"):
        load_update_model(path)


def test_rejects_unreachable_state(tmp_path: Path) -> None:
    path = altered(tmp_path, "    cancelled:\n    - idle", "    cancelled:\n    - idle\n    orphaned:\n    - idle")
    with pytest.raises(UpdateModelError, match="inaccessibles"):
        load_update_model(path)


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    plan = create_update_model_plan(rootfs(tmp_path), ROOT / "config/update-model.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(UpdateModelError, match="enllaç simbòlic"):
        UpdateModelInstaller().install(plan)


def test_cli_supports_update_model(tmp_path: Path) -> None:
    assert build_parser().parse_args(["configure-update-model", "--dry-run"]).command == "configure-update-model"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/update-model.yaml").write_text((ROOT / "config/update-model.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-update-model", "--dry-run"]) == 0
