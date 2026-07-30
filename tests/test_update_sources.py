from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.update_sources import (
    UpdateSourcesError, UpdateSourcesInstaller, create_update_sources_plan, load_update_sources,
)

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path):
    path = tmp_path / ".build/rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path, old, new):
    path = tmp_path / "sources.yaml"
    path.write_text((ROOT / "config/update-sources.yaml").read_text().replace(old, new))
    return path


def test_loads_xms_and_usb_sources():
    policy = load_update_sources(ROOT / "config/update-sources.yaml")
    assert policy["xms"]["enabled"] and policy["usb"]["enabled"]


def test_manifest_is_stable(tmp_path):
    manifest = create_update_sources_plan(rootfs(tmp_path), ROOT / "config/update-sources.yaml").manifest()
    assert manifest["sources"] == ["xms", "usb"] and manifest["fail_closed"] is True


def test_installs_policy_state_runtime_and_udev(tmp_path):
    paths = UpdateSourcesInstaller().install(create_update_sources_plan(rootfs(tmp_path), ROOT / "config/update-sources.yaml"))
    policy, state, audit, inbox, quarantine, runner, service, udev = paths
    assert json.loads(state.read_text())["status"] == "idle"
    assert "import-source" in runner.read_text()
    assert "ProtectSystem=strict" in service.read_text()
    assert "xaac-update" in udev.read_text()
    assert inbox.is_dir() and quarantine.is_dir() and audit.stat().st_mode & 0o777 == 0o640
    assert policy.stat().st_mode & 0o777 == 0o640


def test_installation_is_idempotent(tmp_path):
    plan = create_update_sources_plan(rootfs(tmp_path), ROOT / "config/update-sources.yaml")
    installer = UpdateSourcesInstaller()
    paths = installer.install(plan)
    before = [(p.read_bytes() if p.is_file() else p.stat().st_mode & 0o777) for p in paths]
    installer.install(plan)
    assert before == [(p.read_bytes() if p.is_file() else p.stat().st_mode & 0o777) for p in paths]


def test_dry_run_does_not_write(tmp_path):
    paths = UpdateSourcesInstaller().install(create_update_sources_plan(rootfs(tmp_path), ROOT / "config/update-sources.yaml"), dry_run=True)
    assert len(paths) == 8 and not any(path.exists() for path in paths)


def test_rejects_unsigned_xms_commands(tmp_path):
    with pytest.raises(UpdateSourcesError, match="autenticació XMS"):
        load_update_sources(altered(tmp_path, "require_command_signature: true", "require_command_signature: false"))


def test_rejects_replayable_xms_commands(tmp_path):
    with pytest.raises(UpdateSourcesError, match="autenticació XMS"):
        load_update_sources(altered(tmp_path, "reject_replay: true", "reject_replay: false"))


def test_rejects_unsigned_usb_package(tmp_path):
    with pytest.raises(UpdateSourcesError, match="paquet USB"):
        load_update_sources(altered(tmp_path, "require_detached_signature: true", "require_detached_signature: false"))


def test_rejects_processing_usb_in_place(tmp_path):
    with pytest.raises(UpdateSourcesError, match="paquet USB"):
        load_update_sources(altered(tmp_path, "copy_before_processing: true", "copy_before_processing: false"))


def test_rejects_non_fail_closed_verification(tmp_path):
    with pytest.raises(UpdateSourcesError, match="Verificació"):
        load_update_sources(altered(tmp_path, "fail_closed: true", "fail_closed: false"))


def test_rejects_symlink_destination(tmp_path):
    plan = create_update_sources_plan(rootfs(tmp_path), ROOT / "config/update-sources.yaml")
    target = plan.output("state")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(UpdateSourcesError, match="enllaç simbòlic"):
        UpdateSourcesInstaller().install(plan)


def test_cli_supports_update_sources(tmp_path):
    assert build_parser().parse_args(["configure-update-sources", "--dry-run"]).command == "configure-update-sources"
    rootfs(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/update-sources.yaml").write_text((ROOT / "config/update-sources.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-update-sources", "--dry-run"]) == 0
