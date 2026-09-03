from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.systemd_configuration import (
    SystemdConfigurationError,
    SystemdConfigurator,
    create_systemd_configuration_plan,
)


def config(tmp_path: Path, **updates: object) -> Path:
    payload: dict[str, object] = {
        "default_target": "multi-user.target",
        "console_getty": True,
        "journald": {"storage": "persistent", "system_max_use": "96M", "runtime_max_use": "32M", "max_retention_sec": "7day", "compress": True},
        "tmpfiles": [{"path": "/var/lib/xaac", "type": "d", "mode": "0755", "user": "root", "group": "root", "age": "-"}],
        "enable_services": ["systemd-journald.service"],
        "disable_services": ["apt-daily.service"],
        "mask_services": ["sleep.target"],
    }
    payload.update(updates)
    path = tmp_path / "systemd.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def rootfs(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    (root / "etc").mkdir(parents=True)
    (root / "etc/debian_version").write_text("13\n")
    unitdir = root / "lib/systemd/system"
    unitdir.mkdir(parents=True)
    for name in ("multi-user.target", "systemd-journald.service", "getty@.service"):
        (unitdir / name).write_text("[Unit]\n")
    return root


def test_plan_loads_valid_configuration(tmp_path: Path) -> None:
    plan = create_systemd_configuration_plan(tmp_path / "rootfs", config(tmp_path))
    assert plan.default_target == "multi-user.target"
    assert plan.tmpfiles[0].render() == "d /var/lib/xaac 0755 root root - -"
    assert plan.to_manifest()["journald"]["system_max_use"] == "96M"  # type: ignore[index]


@pytest.mark.parametrize("field", ["default_target", "console_getty", "journald", "tmpfiles", "enable_services", "disable_services", "mask_services"])
def test_missing_or_invalid_required_fields(tmp_path: Path, field: str) -> None:
    replacements: dict[str, object] = {
        "default_target": "bad",
        "console_getty": "yes",
        "journald": [],
        "tmpfiles": {},
        "enable_services": "x",
        "disable_services": "x",
        "mask_services": "x",
    }
    with pytest.raises(SystemdConfigurationError):
        create_systemd_configuration_plan(tmp_path / "rootfs", config(tmp_path, **{field: replacements[field]}))


def test_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    with pytest.raises(SystemdConfigurationError, match="Claus desconegudes"):
        create_systemd_configuration_plan(tmp_path / "rootfs", config(tmp_path, surprise=True))


def test_rejects_unknown_journald_key(tmp_path: Path) -> None:
    with pytest.raises(SystemdConfigurationError, match="journald"):
        create_systemd_configuration_plan(tmp_path / "rootfs", config(tmp_path, journald={"storage": "persistent", "system_max_use": "1M", "runtime_max_use": "1M", "max_retention_sec": "1day", "compress": True, "x": 1}))


def test_rejects_unsafe_tmpfiles_path(tmp_path: Path) -> None:
    with pytest.raises(SystemdConfigurationError, match="Ruta tmpfiles"):
        create_systemd_configuration_plan(tmp_path / "rootfs", config(tmp_path, tmpfiles=[{"path": "/var/../etc", "type": "d", "mode": "0755", "user": "root", "group": "root", "age": "-"}]))


def test_rejects_overlapping_unit_policies(tmp_path: Path) -> None:
    with pytest.raises(SystemdConfigurationError, match="incompatibles"):
        create_systemd_configuration_plan(tmp_path / "rootfs", config(tmp_path, enable_services=["sleep.target"]))


def test_dry_run_does_not_modify_rootfs(tmp_path: Path) -> None:
    plan = create_systemd_configuration_plan(tmp_path / "rootfs", config(tmp_path))
    result = SystemdConfigurator(geteuid=lambda: 1000).execute(plan, tmp_path / "log", dry_run=True)
    assert not result.executed
    assert "DRY-RUN" in result.log_path.read_text()
    assert not plan.journald_path.exists()


def test_real_execution_requires_root(tmp_path: Path) -> None:
    plan = create_systemd_configuration_plan(rootfs(tmp_path), config(tmp_path))
    with pytest.raises(SystemdConfigurationError, match="root"):
        SystemdConfigurator(geteuid=lambda: 1000).execute(plan, tmp_path / "log")


def test_real_execution_writes_files_and_links(tmp_path: Path) -> None:
    root = rootfs(tmp_path)
    plan = create_systemd_configuration_plan(root, config(tmp_path))
    result = SystemdConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "log")
    assert result.executed
    assert "Storage=persistent" in plan.journald_path.read_text()
    assert "d /var/lib/xaac" in plan.tmpfiles_path.read_text()
    assert plan.default_target_path.is_symlink()
    assert (root / "etc/systemd/system/multi-user.target.wants/systemd-journald.service").is_symlink()
    assert (root / "etc/systemd/system/sleep.target").readlink() == Path("/dev/null")
    assert (root / "etc/systemd/system/getty.target.wants/getty@tty1.service").is_symlink()


def test_execution_removes_disabled_links(tmp_path: Path) -> None:
    root = rootfs(tmp_path)
    link = root / "etc/systemd/system/multi-user.target.wants/apt-daily.service"
    link.parent.mkdir(parents=True)
    link.symlink_to("/lib/systemd/system/apt-daily.service")
    plan = create_systemd_configuration_plan(root, config(tmp_path))
    SystemdConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "log")
    assert not link.exists()


def test_execution_rejects_missing_systemd_rootfs(tmp_path: Path) -> None:
    plan = create_systemd_configuration_plan(tmp_path / "rootfs", config(tmp_path))
    with pytest.raises(SystemdConfigurationError, match="Debian"):
        SystemdConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "log")


def test_execution_rejects_missing_enabled_unit(tmp_path: Path) -> None:
    root = rootfs(tmp_path)
    plan = create_systemd_configuration_plan(root, config(tmp_path, enable_services=["missing.service"]))
    with pytest.raises(SystemdConfigurationError, match="No existeix"):
        SystemdConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "log")


def test_atomic_write_rejects_symlink(tmp_path: Path) -> None:
    root = rootfs(tmp_path)
    plan = create_systemd_configuration_plan(root, config(tmp_path))
    plan.journald_path.parent.mkdir(parents=True)
    plan.journald_path.symlink_to(tmp_path / "outside")
    with pytest.raises(SystemdConfigurationError, match="enllaç simbòlic"):
        SystemdConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "log")
