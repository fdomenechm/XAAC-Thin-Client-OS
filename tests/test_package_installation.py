from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xaac_thin_client_os.package_installation import (
    PackageInstallationError,
    PackageInstaller,
    create_package_installation_plan,
)


def _plan(tmp_path: Path):  # type: ignore[no-untyped-def]
    return create_package_installation_plan(
        tmp_path / "run" / "rootfs",
        ("systemd", "apt", "systemd", "ca-certificates"),
        ("task-desktop",),
    )


def _prepare_rootfs(rootfs: Path) -> None:
    for path in (
        rootfs / "etc" / "debian_version",
        rootfs / "usr" / "bin" / "apt-get",
        rootfs / "etc" / "apt" / "sources.list.d" / "xaac.sources",
        rootfs / "etc" / "apt" / "apt.conf.d" / "99xaac-minimal",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")


def test_plan_sorts_and_deduplicates_packages(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert plan.packages == ("apt", "ca-certificates", "systemd")
    assert plan.excluded == ("task-desktop",)


def test_plan_rejects_unsafe_rootfs() -> None:
    with pytest.raises(PackageInstallationError, match="insegur"):
        create_package_installation_plan(Path("/rootfs"), ("apt",))


def test_plan_rejects_empty_package_list(tmp_path: Path) -> None:
    with pytest.raises(PackageInstallationError, match="buida"):
        create_package_installation_plan(tmp_path / "run/rootfs", ())


def test_plan_rejects_invalid_package_names(tmp_path: Path) -> None:
    with pytest.raises(PackageInstallationError, match="no vàlid"):
        create_package_installation_plan(tmp_path / "run/rootfs", ("--bad",))


def test_plan_rejects_included_and_excluded_overlap(tmp_path: Path) -> None:
    with pytest.raises(PackageInstallationError, match="simultàniament"):
        create_package_installation_plan(tmp_path / "run/rootfs", ("apt",), ("apt",))


def test_commands_are_minimal_and_noninteractive(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert plan.update_command()[-2:] == ("apt-get", "update")
    command = plan.install_command()
    assert "--no-install-recommends" in command
    assert "--no-install-suggests" in command
    assert command[-3:] == ("apt", "ca-certificates", "systemd")


def test_manifest_contains_auditable_plan(tmp_path: Path) -> None:
    payload = _plan(tmp_path).to_manifest()
    assert payload["package_count"] == 3
    assert payload["noninteractive"] is True
    assert payload["install_recommends"] is False


def test_dry_run_does_not_require_root_or_rootfs(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    log = tmp_path / "logs/packages.log"
    result = PackageInstaller(geteuid=lambda: 1000).execute(plan, log, dry_run=True)
    assert result.executed is False
    assert result.commands_executed == 0
    text = log.read_text(encoding="utf-8")
    assert "DRY-RUN" in text
    assert "apt-get update" in text
    assert "apt-get install" in text


def test_real_installation_requires_root(tmp_path: Path) -> None:
    with pytest.raises(PackageInstallationError, match="root"):
        PackageInstaller(geteuid=lambda: 1000).execute(_plan(tmp_path), tmp_path / "log")


def test_real_installation_requires_prepared_rootfs(tmp_path: Path) -> None:
    with pytest.raises(PackageInstallationError, match="falten"):
        PackageInstaller(geteuid=lambda: 0).execute(_plan(tmp_path), tmp_path / "log")


def test_real_installation_runs_update_then_install(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    _prepare_rootfs(plan.rootfs)
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((tuple(command), kwargs))
        return subprocess.CompletedProcess(command, 0)

    result = PackageInstaller(geteuid=lambda: 0, runner=runner).execute(
        plan, tmp_path / "logs/packages.log"
    )
    assert result.executed is True
    assert result.commands_executed == 2
    assert calls[0][0] == plan.update_command()
    assert calls[1][0] == plan.install_command()
    assert calls[0][1]["env"]["DEBIAN_FRONTEND"] == "noninteractive"  # type: ignore[index]


def test_called_process_error_is_wrapped(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    _prepare_rootfs(plan.rootfs)

    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(100, command)

    with pytest.raises(PackageInstallationError, match="codi 100"):
        PackageInstaller(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "packages.log")


def test_os_error_is_wrapped(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    _prepare_rootfs(plan.rootfs)

    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("chroot")

    with pytest.raises(PackageInstallationError, match="No s'ha pogut executar"):
        PackageInstaller(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "packages.log")
