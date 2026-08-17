from pathlib import Path
import json

import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.update_model import (
    UpdateModelError,
    UpdateModelInstaller,
    create_update_model_plan,
    load_update_model,
    resolve_update_channel,
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


def test_loads_phase_10_2_update_architecture() -> None:
    model = load_update_model(ROOT / "config/update-model.yaml")
    assert model["schema_version"] == 2
    assert model["phase"] == "10.2"
    assert [component["package"] for component in model["components"]] == [
        "xaac-thinclient",
        "xaac-thin-client-vpn",
        "xaac-agent",
    ]
    assert model["manifest"]["require_detached_signature"] is True
    assert model["version_policy"]["allow_downgrade"] is False
    assert model["version_policy"]["allow_os_version_change"] is False


def test_manifest_is_stable(tmp_path: Path) -> None:
    manifest = create_update_model_plan(rootfs(tmp_path), ROOT / "config/update-model.yaml").manifest()
    assert manifest == {
        "schema_version": 2,
        "model_id": "xaac-update-architecture-v1",
        "phase": "10.2",
        "hardware_profile": "wyse3040",
        "architecture": "amd64",
        "component_count": 3,
        "manifest_schema": "xaac-update-manifest/v1",
        "downgrades_allowed": False,
    }


def test_maps_image_build_channels_to_update_channels() -> None:
    model = load_update_model(ROOT / "config/update-model.yaml")
    assert resolve_update_channel(model, "development") == "laboratory"
    assert resolve_update_channel(model, "testing") == "pilot"
    assert resolve_update_channel(model, "candidate") == "pilot"
    assert resolve_update_channel(model, "stable") == "production"
    assert resolve_update_channel(model, "long-term") == "production"


def test_installs_policy_and_initial_state_with_safe_permissions(tmp_path: Path) -> None:
    plan = create_update_model_plan(rootfs(tmp_path), ROOT / "config/update-model.yaml")
    policy, state = UpdateModelInstaller().install(plan)
    installed_policy = json.loads(policy.read_text())
    assert installed_policy["manifest"]["hash_algorithm"] == "sha256"
    assert "package_config" not in installed_policy["components"][0]
    assert json.loads(state.read_text())["status"] == "idle"
    assert policy.stat().st_mode & 0o777 == 0o640
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


def test_rejects_wrong_production_package_name(tmp_path: Path) -> None:
    path = altered(tmp_path, "package: xaac-thinclient", "package: xaac-thin-client")
    with pytest.raises(UpdateModelError, match="paquets de producció"):
        load_update_model(path)


def test_rejects_relaxed_downgrade_policy(tmp_path: Path) -> None:
    path = altered(tmp_path, "allow_downgrade: false", "allow_downgrade: true")
    with pytest.raises(UpdateModelError, match="downgrades"):
        load_update_model(path)


def test_rejects_incomplete_atomic_set(tmp_path: Path) -> None:
    path = altered(tmp_path, "    - xaac-agent\n", "")
    with pytest.raises(UpdateModelError, match="atòmic"):
        load_update_model(path)


def test_rejects_unsigned_manifest_policy(tmp_path: Path) -> None:
    path = altered(tmp_path, "require_detached_signature: true", "require_detached_signature: false")
    with pytest.raises(UpdateModelError, match="fail-closed"):
        load_update_model(path)


def test_rejects_too_little_preflight_space(tmp_path: Path) -> None:
    path = altered(tmp_path, "minimum_free_bytes: 536870912", "minimum_free_bytes: 1024")
    with pytest.raises(UpdateModelError, match="Espai lliure"):
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
