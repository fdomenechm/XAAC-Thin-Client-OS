from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaac_thin_client_os.emmc_support import (
    EmmcConfigurator,
    EmmcDetector,
    EmmcDevice,
    EmmcSupportError,
    compare_emmc,
    create_emmc_configuration_plan,
    load_emmc_profile,
    write_emmc_report,
)


def write(root: Path, relative: str, value: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def fake_emmc(root: Path, *, discard: int = 4194304, removable: int = 0, rotational: int = 0) -> None:
    write(root, "sys/class/block/mmcblk0/size", "15269888\n")
    write(root, "sys/class/block/mmcblk0/removable", f"{removable}\n")
    write(root, "sys/class/block/mmcblk0/queue/rotational", f"{rotational}\n")
    write(root, "sys/class/block/mmcblk0/queue/logical_block_size", "512\n")
    write(root, "sys/class/block/mmcblk0/queue/discard_max_bytes", f"{discard}\n")
    write(root, "sys/class/block/mmcblk0/device/type", "MMC\n")
    write(root, "sys/class/block/mmcblk0/device/cid", "1234567890abcdef\n")
    write(root, "sys/class/block/mmcblk0p1/size", "1000\n")
    write(root, "proc/modules", "mmc_block 65536 1 - Live 0x0\nsdhci 81920 1 - Live 0x0\n")


def device(**changes: object) -> EmmcDevice:
    values: dict[str, object] = {
        "name": "mmcblk0",
        "size_mib": 7456,
        "removable": False,
        "rotational": False,
        "logical_block_size": 512,
        "discard_max_bytes": 4194304,
        "device_type": "MMC",
        "cid": "1234",
    }
    values.update(changes)
    return EmmcDevice(**values)  # type: ignore[arg-type]


def test_detects_emmc_properties_and_modules(tmp_path: Path) -> None:
    fake_emmc(tmp_path)
    devices, modules = EmmcDetector(root=tmp_path).detect()
    assert devices == (device(cid="1234567890abcdef"),)
    assert modules == ("mmc_block", "sdhci")


def test_ignores_mmc_partitions_and_other_block_devices(tmp_path: Path) -> None:
    fake_emmc(tmp_path)
    write(tmp_path, "sys/class/block/sda/size", "999999\n")
    devices, _ = EmmcDetector(root=tmp_path).detect()
    assert [item.name for item in devices] == ["mmcblk0"]


def test_missing_sysfs_is_safe(tmp_path: Path) -> None:
    devices, modules = EmmcDetector(root=tmp_path).detect()
    assert devices == () and modules == ()


def test_invalid_integer_fields_fall_back_safely(tmp_path: Path) -> None:
    fake_emmc(tmp_path)
    write(tmp_path, "sys/class/block/mmcblk0/size", "invalid\n")
    write(tmp_path, "sys/class/block/mmcblk0/queue/discard_max_bytes", "invalid\n")
    devices, _ = EmmcDetector(root=tmp_path).detect()
    assert devices[0].size_mib == 0
    assert not devices[0].trim_supported


def test_profile_loads(project_root: Path) -> None:
    profile = load_emmc_profile(project_root / "config/emmc.yaml")
    assert profile["profile"] == "wyse3040"
    assert profile["trim"]["timer"] == "fstrim.timer"


@pytest.mark.parametrize("content", ["schema_version: 99\n", "[]\n", "schema_version: 1\nprofile: x\n"])
def test_invalid_profiles_are_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "emmc.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(EmmcSupportError, match="Perfil eMMC|seccions"):
        load_emmc_profile(path)


def test_compatible_emmc_passes(project_root: Path) -> None:
    report = compare_emmc((device(),), ("mmc_block",), load_emmc_profile(project_root / "config/emmc.yaml"))
    assert report.compatible
    assert report.selected_device == device()
    assert all(check.status == "pass" for check in report.checks)


def test_largest_candidate_is_selected(project_root: Path) -> None:
    small = device(name="mmcblk0", size_mib=4000)
    large = device(name="mmcblk1", size_mib=7456)
    report = compare_emmc((small, large), ("sdhci",), load_emmc_profile(project_root / "config/emmc.yaml"))
    assert report.selected_device == large


@pytest.mark.parametrize(
    "candidate,modules,failed",
    [
        (None, ("mmc_block",), "device"),
        (device(size_mib=6000), ("mmc_block",), "capacity"),
        (device(removable=True), ("mmc_block",), "non-removable"),
        (device(rotational=True), ("mmc_block",), "non-rotational"),
        (device(logical_block_size=4096), ("mmc_block",), "sector-size"),
        (device(discard_max_bytes=0), ("mmc_block",), "trim"),
        (device(), ("i915",), "kernel-driver"),
    ],
)
def test_incompatible_conditions_are_reported(project_root: Path, candidate: EmmcDevice | None, modules: tuple[str, ...], failed: str) -> None:
    devices = () if candidate is None else (candidate,)
    report = compare_emmc(devices, modules, load_emmc_profile(project_root / "config/emmc.yaml"))
    assert not report.compatible
    assert next(check for check in report.checks if check.name == failed).status == "fail"


def test_configuration_plan_is_deterministic(tmp_path: Path, project_root: Path) -> None:
    plan = create_emmc_configuration_plan(tmp_path / "build/rootfs", project_root / "config/emmc.yaml")
    assert plan.modules == ("mmc_block", "sdhci", "sdhci_acpi", "sdhci_pci")
    assert plan.timer_name == "fstrim.timer"
    assert str(plan.enable_link).endswith("timers.target.wants/fstrim.timer")
    assert plan.to_manifest()["timer"] == "fstrim.timer"


def test_configuration_plan_rejects_unsafe_rootfs(project_root: Path) -> None:
    with pytest.raises(EmmcSupportError, match="Rootfs insegur"):
        create_emmc_configuration_plan(Path("/"), project_root / "config/emmc.yaml")


def test_dry_run_writes_nothing(tmp_path: Path, project_root: Path) -> None:
    plan = create_emmc_configuration_plan(tmp_path / "build/rootfs", project_root / "config/emmc.yaml")
    result = EmmcConfigurator().execute(plan, dry_run=True)
    assert not result.executed and result.files_written == ()
    assert not plan.rootfs.exists()


def test_execution_writes_files_and_enables_timer(tmp_path: Path, project_root: Path) -> None:
    rootfs = tmp_path / "build/rootfs"
    unit = rootfs / "usr/lib/systemd/system/fstrim.timer"
    write(rootfs, "usr/lib/systemd/system/fstrim.timer", "[Timer]\n")
    plan = create_emmc_configuration_plan(rootfs, project_root / "config/emmc.yaml")
    result = EmmcConfigurator().execute(plan)
    assert result.executed and len(result.files_written) == 3
    modules = rootfs / "etc/modules-load.d/xaac-emmc.conf"
    assert "mmc_block" in modules.read_text(encoding="utf-8")
    link = rootfs / "etc/systemd/system/timers.target.wants/fstrim.timer"
    assert link.is_symlink()
    assert link.readlink() == Path("/usr/lib/systemd/system/fstrim.timer")


def test_execution_accepts_lib_systemd_unit(tmp_path: Path, project_root: Path) -> None:
    rootfs = tmp_path / "build/rootfs"
    write(rootfs, "lib/systemd/system/fstrim.timer", "[Timer]\n")
    plan = create_emmc_configuration_plan(rootfs, project_root / "config/emmc.yaml")
    EmmcConfigurator().execute(plan)
    assert (rootfs / "etc/systemd/system/timers.target.wants/fstrim.timer").readlink() == Path("/lib/systemd/system/fstrim.timer")


def test_missing_timer_unit_is_rejected(tmp_path: Path, project_root: Path) -> None:
    plan = create_emmc_configuration_plan(tmp_path / "build/rootfs", project_root / "config/emmc.yaml")
    with pytest.raises(EmmcSupportError, match="unitat systemd"):
        EmmcConfigurator().execute(plan)


def test_conflicting_enable_path_is_rejected(tmp_path: Path, project_root: Path) -> None:
    rootfs = tmp_path / "build/rootfs"
    write(rootfs, "usr/lib/systemd/system/fstrim.timer", "[Timer]\n")
    write(rootfs, "etc/systemd/system/timers.target.wants/fstrim.timer", "not a link\n")
    plan = create_emmc_configuration_plan(rootfs, project_root / "config/emmc.yaml")
    with pytest.raises(EmmcSupportError, match="no és un enllaç"):
        EmmcConfigurator().execute(plan)


def test_wrong_existing_symlink_is_rejected(tmp_path: Path, project_root: Path) -> None:
    rootfs = tmp_path / "build/rootfs"
    write(rootfs, "usr/lib/systemd/system/fstrim.timer", "[Timer]\n")
    link = rootfs / "etc/systemd/system/timers.target.wants/fstrim.timer"
    link.parent.mkdir(parents=True)
    link.symlink_to("/wrong.timer")
    plan = create_emmc_configuration_plan(rootfs, project_root / "config/emmc.yaml")
    with pytest.raises(EmmcSupportError, match="no apunta"):
        EmmcConfigurator().execute(plan)


def test_report_is_written_atomically(tmp_path: Path, project_root: Path) -> None:
    report = compare_emmc((device(),), ("mmc_block",), load_emmc_profile(project_root / "config/emmc.yaml"))
    destination = tmp_path / "reports/emmc.json"
    write_emmc_report(report, destination)
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["compatible"] is True
    assert payload["selected_device"]["path"] == "/dev/mmcblk0"
    assert not destination.with_name("emmc.json.tmp").exists()


def test_report_rejects_symlink(tmp_path: Path, project_root: Path) -> None:
    report = compare_emmc((device(),), ("mmc_block",), load_emmc_profile(project_root / "config/emmc.yaml"))
    target = tmp_path / "target"
    destination = tmp_path / "report.json"
    destination.symlink_to(target)
    with pytest.raises(EmmcSupportError, match="enllaç simbòlic"):
        write_emmc_report(report, destination)
