from __future__ import annotations

from pathlib import Path

import pytest

from xaac_thin_client_os.production_builder import (
    BuildPaths,
    CommandRunner,
    ProductionBuildError,
    ProductionIsoBuilder,
    build_parser,
)


def minimal_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\nversion='1'\n", encoding="utf-8")
    return root


def test_build_paths_rejects_non_project(tmp_path: Path) -> None:
    with pytest.raises(ProductionBuildError):
        BuildPaths.create(tmp_path)


def test_build_paths_are_scoped_to_project(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    paths = BuildPaths.create(root)
    assert paths.rootfs == root / ".build/production/rootfs"
    assert paths.artifacts == root / ".build/artifacts"


def test_parser_accepts_individual_phases() -> None:
    args = build_parser().parse_args(["--phase", "rootfs", "--phase", "configure", "--dry-run"])
    assert args.phase == ["rootfs", "configure"]
    assert args.dry_run is True


def test_command_runner_dry_run_records_command(tmp_path: Path) -> None:
    runner = CommandRunner(tmp_path / "logs", dry_run=True)
    runner.run(["echo", "hello"], phase="sample")
    assert (tmp_path / "logs/sample.log").read_text(encoding="utf-8") == "$ echo hello\n"


def test_command_runner_recreates_logs_after_workspace_cleanup(tmp_path: Path) -> None:
    logs = tmp_path / "production/logs"
    runner = CommandRunner(logs, dry_run=True)
    import shutil
    shutil.rmtree(logs.parent)
    runner.run(["echo", "hello"], phase="after-clean")
    assert (logs / "after-clean.log").read_text(encoding="utf-8") == "$ echo hello\n"


def test_inside_never_uses_host_system_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    assert builder._inside("/usr/lib/systemd/system/getty@.service") == (
        root / ".build/production/rootfs/usr/lib/systemd/system/getty@.service"
    )
    with pytest.raises(ProductionBuildError):
        builder._inside("../../etc/passwd")



def test_inside_allows_existing_absolute_leaf_symlink(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    etc = builder.paths.rootfs / "etc"
    etc.mkdir(parents=True)
    localtime = etc / "localtime"
    localtime.symlink_to("/usr/share/zoneinfo/Europe/Madrid")

    assert builder._inside("/etc/localtime") == localtime


def test_inside_rejects_symlinked_parent_outside_rootfs(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    builder.paths.rootfs.mkdir(parents=True)
    (builder.paths.rootfs / "etc").symlink_to(tmp_path / "outside")

    with pytest.raises(ProductionBuildError, match="directori pare"):
        builder._inside("/etc/hostname")

def test_clean_is_limited_to_production_workspace(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    target = builder.paths.build_root
    target.mkdir(parents=True)
    (target / "file").write_text("x", encoding="utf-8")
    builder.clean()
    assert not target.exists()


def test_rootfs_bootstrap_does_not_install_runtime_packages(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    from types import SimpleNamespace
    builder.settings = SimpleNamespace(
        architecture="amd64",
        components=("main", "non-free-firmware"),
        suite="trixie",
        mirror="https://deb.debian.org/debian",
    )
    builder.dry_run = True
    builder.runner = CommandRunner(builder.paths.logs, dry_run=True)
    builder._save_state = lambda phase: None  # type: ignore[method-assign]
    builder.phase_rootfs()
    command = (builder.paths.logs / "rootfs-debootstrap.log").read_text(encoding="utf-8")
    assert "--components=main,non-free-firmware" in command
    assert "--include=" not in command
    assert "firmware-linux" not in command


def test_apt_sources_include_all_configured_components(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    from types import SimpleNamespace
    builder.settings = SimpleNamespace(
        components=("main", "non-free-firmware"),
        suite="trixie",
        mirror="https://deb.debian.org/debian",
    )
    builder._write_apt_sources()
    sources = (builder.paths.rootfs / "etc/apt/sources.list").read_text(encoding="utf-8")
    assert "trixie main non-free-firmware" in sources
    assert "trixie-security main non-free-firmware" in sources


def test_iso_phase_does_not_forward_invalid_volume_option_to_xorriso(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    from types import SimpleNamespace
    builder.settings = SimpleNamespace(
        output_name="xaac.iso",
        kernel_parameters=(),
        volume_id="XAAC_TC_OS",
        live_username="xaac-kiosk",
        live_user_fullname="XAAC Kiosk",
    )
    builder.dry_run = True
    builder.runner = CommandRunner(builder.paths.logs, dry_run=True)
    builder._save_state = lambda phase: None  # type: ignore[method-assign]

    boot = builder.paths.build_root / "boot"
    boot.mkdir(parents=True)
    (boot / "vmlinuz").write_bytes(b"kernel")
    (boot / "initrd.img").write_bytes(b"initrd")
    (builder.paths.build_root / "rootfs.squashfs").write_bytes(b"squashfs")

    builder.phase_iso()

    command = (builder.paths.logs / "iso-grub-mkrescue.log").read_text(encoding="utf-8")
    assert "grub-mkrescue -o" in command
    assert "-- -V" not in command
    assert "XAAC_TC_OS" not in command

    grub = (builder.paths.staging / "boot/grub/grub.cfg").read_text(encoding="utf-8")
    assert "username=xaac-kiosk" in grub
    assert "user-fullname=XAAC_Kiosk" in grub
    assert "username=user" not in grub


def test_production_kiosk_account_has_login_shell() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "--create-home --shell /bin/bash --gid xaac-kiosk xaac-kiosk" in source
    assert '["usermod", "--shell", "/bin/bash", "xaac-kiosk"]' in source
    assert "--shell /usr/sbin/nologin --gid xaac-kiosk" not in source


def test_localization_defaults_are_catalan_with_spanish_keyboard() -> None:
    project = Path(__file__).resolve().parents[1]
    localization = (project / "config/localization.yaml").read_text(encoding="utf-8")
    packages = (project / "config/packages.yaml").read_text(encoding="utf-8")
    iso = (project / "config/iso-builder.yaml").read_text(encoding="utf-8")

    assert "locale: ca_ES.UTF-8" in localization
    assert "layout: es" in localization
    assert 'variant: ""' in localization
    assert "keyboard-configuration" in packages
    assert "console-setup-linux" in packages
    assert "locales=ca_ES.UTF-8" in iso
    assert "keyboard-layouts=es" in iso
    assert "timezone=Europe/Madrid" in iso


def test_production_builder_reconfigures_keyboard_noninteractively() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "dpkg-reconfigure keyboard-configuration" in source
    assert "DEBIAN_FRONTEND=noninteractive" in source
    assert 'update-locale", f"LANG={self.settings.locale}' in source
