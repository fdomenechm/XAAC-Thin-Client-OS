from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.first_boot import (
    FirstBootError,
    FirstBootInstaller,
    FirstBootRunner,
    load_first_boot_profile,
    validate_hardware,
)


def _profile(tmp_path: Path) -> Path:
    target = tmp_path / "first-boot.yaml"
    target.write_text(Path("config/first-boot.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "device-identity.yaml").write_text(Path("config/device-identity.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _rootfs(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    (root / "sys/class/dmi/id").mkdir(parents=True)
    (root / "sys/class/dmi/id/product_name").write_text("Wyse 3040 Thin Client\n")
    (root / "proc").mkdir()
    (root / "proc/meminfo").write_text("MemTotal:        2015232 kB\n")
    (root / "sys/block/mmcblk0").mkdir(parents=True)
    return root


class IdentityManager:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, root: Path, profile: Path):
        self.calls += 1
        return SimpleNamespace(uuid="11111111-2222-4333-8444-555555555555")


def test_profile_is_valid() -> None:
    profile = load_first_boot_profile(Path("config/first-boot.yaml"))
    assert profile["hardware"]["minimum_ram_mib"] == 1800
    assert profile["service"]["wanted_by"] == "multi-user.target"


def test_profile_rejects_relative_path(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/first-boot.yaml").read_text())
    data["service"]["state_path"] = "state.json"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(FirstBootError, match="Ruta insegura"):
        load_first_boot_profile(path)


def test_profile_rejects_world_writable_state(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/first-boot.yaml").read_text())
    data["security"]["state_mode"] = "0642"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(FirstBootError, match="massa permissiu"):
        load_first_boot_profile(path)


def test_hardware_validation_accepts_wyse(tmp_path: Path) -> None:
    report = validate_hardware(_rootfs(tmp_path), load_first_boot_profile(_profile(tmp_path)))
    assert report.product == "Wyse 3040 Thin Client"
    assert report.ram_mib >= 1900
    assert report.emmc == "/sys/block/mmcblk0"


def test_hardware_validation_rejects_wrong_model(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    (root / "sys/class/dmi/id/product_name").write_text("Other computer\n")
    with pytest.raises(FirstBootError, match="no compatible"):
        validate_hardware(root, load_first_boot_profile(_profile(tmp_path)))


def test_installer_dry_run_does_not_write(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    paths = FirstBootInstaller().install(root, _profile(tmp_path), dry_run=True)
    assert len(paths) == 4
    assert not (root / "usr/lib/systemd/system/xaac-first-boot.service").exists()


def test_installer_writes_hardened_enabled_service(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    paths = FirstBootInstaller().install(root, _profile(tmp_path))
    unit = root / "usr/lib/systemd/system/xaac-first-boot.service"
    text = unit.read_text()
    assert "Before=xaac-agent.service greetd.service" in text
    assert "ProtectSystem=strict" in text
    assert "ConditionPathExists=!/var/lib/xaac-agent/first-boot/completed" in text
    assert paths[-1].is_symlink()
    assert (root / "etc/xaac/device-identity.yaml").is_file()


def test_runner_completes_and_is_idempotent(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    identity_profile = tmp_path / "identity.yaml"
    identity_profile.write_text("unused")
    manager = IdentityManager()
    runner = FirstBootRunner()
    first = runner.run(root, _profile(tmp_path), identity_profile=identity_profile, identity_manager=manager)
    second = runner.run(root, _profile(tmp_path), identity_profile=identity_profile, identity_manager=manager)
    assert first["status"] == "completed"
    assert second == first
    assert manager.calls == 1
    assert (root / "var/lib/xaac-agent/first-boot/completed").exists()


def test_runner_records_failure_without_completion(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    (root / "proc/meminfo").write_text("MemTotal: 100000 kB\n")
    with pytest.raises(FirstBootError, match="Memòria insuficient"):
        FirstBootRunner().run(root, _profile(tmp_path), identity_profile=tmp_path / "identity.yaml", identity_manager=IdentityManager())
    state = json.loads((root / "var/lib/xaac-agent/first-boot/state.json").read_text())
    assert state["status"] == "failed"
    assert not (root / "var/lib/xaac-agent/first-boot/completed").exists()


def test_cli_exposes_first_boot_command() -> None:
    args = build_parser().parse_args(["configure-first-boot", "--dry-run"])
    assert args.command == "configure-first-boot"
    assert args.dry_run is True
