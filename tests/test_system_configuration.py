from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xaac_thin_client_os.system_configuration import (
    SystemConfigurationError,
    SystemConfigurator,
    create_system_configuration_plan,
)


def _config(path: Path, *, hostname: str = "xaac-thin-client") -> Path:
    path.write_text(
        f"schema_version: 1\nhostname: {hostname}\ntimezone: Europe/Madrid\n"
        "locale: ca_ES.UTF-8\nfallback_locales:\n  - es_ES.UTF-8\n  - en_US.UTF-8\n",
        encoding="utf-8",
    )
    return path


def _plan(tmp_path: Path):  # type: ignore[no-untyped-def]
    return create_system_configuration_plan(tmp_path / "runs/build/rootfs", _config(tmp_path / "system.yaml"))


def _prepare(plan) -> None:  # type: ignore[no-untyped-def]
    for path in (
        plan.rootfs / "etc/debian_version",
        plan.rootfs / "usr/sbin/locale-gen",
        plan.rootfs / "usr/share/zoneinfo/Europe/Madrid",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")


def test_plan_loads_identity_and_locales(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert plan.hostname == "xaac-thin-client"
    assert plan.timezone == "Europe/Madrid"
    assert plan.locales == ("ca_ES.UTF-8", "es_ES.UTF-8", "en_US.UTF-8")


def test_plan_rejects_unsafe_rootfs(tmp_path: Path) -> None:
    with pytest.raises(SystemConfigurationError, match="insegura"):
        create_system_configuration_plan(Path("/rootfs"), _config(tmp_path / "system.yaml"))


def test_plan_rejects_invalid_hostname(tmp_path: Path) -> None:
    with pytest.raises(SystemConfigurationError, match="hostname"):
        create_system_configuration_plan(tmp_path / "runs/build/rootfs", _config(tmp_path / "system.yaml", hostname="Bad_Name"))


def test_plan_rejects_unknown_keys(tmp_path: Path) -> None:
    path = _config(tmp_path / "system.yaml")
    path.write_text(path.read_text() + "unknown: true\n", encoding="utf-8")
    with pytest.raises(SystemConfigurationError, match="desconegudes"):
        create_system_configuration_plan(tmp_path / "runs/build/rootfs", path)


def test_dry_run_does_not_require_rootfs_or_root(tmp_path: Path) -> None:
    result = SystemConfigurator(geteuid=lambda: 1000).execute(_plan(tmp_path), tmp_path / "log", dry_run=True)
    assert result.executed is False
    assert result.commands_executed == 0
    assert "DRY-RUN" in result.log_path.read_text(encoding="utf-8")


def test_real_configuration_requires_root(tmp_path: Path) -> None:
    with pytest.raises(SystemConfigurationError, match="root"):
        SystemConfigurator(geteuid=lambda: 1000).execute(_plan(tmp_path), tmp_path / "log")


def test_real_configuration_requires_rootfs_files(tmp_path: Path) -> None:
    with pytest.raises(SystemConfigurationError, match="falten"):
        SystemConfigurator(geteuid=lambda: 0).execute(_plan(tmp_path), tmp_path / "log")


def test_real_configuration_writes_files_and_runs_locale_gen(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    _prepare(plan)
    calls = []
    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)
    result = SystemConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "log")
    assert result.executed is True
    assert (plan.rootfs / "etc/hostname").read_text() == "xaac-thin-client\n"
    assert 'LANG="ca_ES.UTF-8"' in (plan.rootfs / "etc/default/locale").read_text()
    assert (plan.rootfs / "etc/localtime").is_symlink()
    assert calls == [plan.locale_command()]


def test_symbolic_destination_is_rejected(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    _prepare(plan)
    target = plan.rootfs / "etc/hostname"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to("/tmp/hostname")
    with pytest.raises(SystemConfigurationError, match="simbòlic"):
        SystemConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "log")


def test_locale_gen_error_is_wrapped(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    _prepare(plan)
    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(1, command)
    with pytest.raises(SystemConfigurationError, match="codi 1"):
        SystemConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "log")


def test_default_locale_internal_symlink_is_supported(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    _prepare(plan)
    target = plan.rootfs / "etc/default/locale"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to("/etc/locale.conf")
    calls = []
    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)
    SystemConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "log")
    assert target.is_symlink()
    assert 'LANG="ca_ES.UTF-8"' in (plan.rootfs / "etc/locale.conf").read_text()
