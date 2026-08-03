from __future__ import annotations

from pathlib import Path
import subprocess

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
    assert "locales=ca_ES.UTF-8" not in iso
    assert "keyboard-layouts=es" not in iso
    assert "timezone=Europe/Madrid" not in iso
    assert "live-config.nocomponents" in iso
    assert "live-config.nottyautologin" in iso
    assert " components " not in iso


def test_production_builder_reconfigures_keyboard_noninteractively() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "dpkg-reconfigure keyboard-configuration" in source
    assert "DEBIAN_FRONTEND=noninteractive" in source
    assert 'update-locale", f"LANG={self.settings.locale}' in source


def test_installer_step2_detects_and_selects_disks_without_writing() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "/usr/local/sbin/xaac-installer-welcome" in source
    assert "ConditionKernelCommandLine=xaac.mode=installer" in source
    assert "Conflicts=getty@tty1.service" in source
    assert "TTYPath=/dev/tty1" in source
    assert "Aquest pas NO particiona, formata ni modifica cap disc." in source
    assert "lsblk -dnP -o NAME,SIZE,MODEL,TYPE,RO,RM" in source
    assert '${TYPE:-}' in source
    assert 'case $base in loop*|ram*|zram*|sr*) continue ;; esac' in source
    assert "Seleccioneu el número del disc" in source
    assert "No s’ha escrit cap dada al disc seleccionat." in source
    assert '["systemctl", "enable", "xaac-installer-welcome.service"]' in source


def test_installer_grub_entry_uses_multi_user_target(tmp_path: Path) -> None:
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
    grub = (builder.paths.staging / "boot/grub/grub.cfg").read_text(encoding="utf-8")
    installer_line = next(line for line in grub.splitlines() if "xaac.mode=installer" in line)
    assert "systemd.unit=multi-user.target" in installer_line
    diagnostics_line = next(line for line in grub.splitlines() if "xaac.mode=diagnostics" in line)
    assert "systemd.unit=multi-user.target" not in diagnostics_line


def test_cleanup_chroot_mounts_is_scoped_and_deepest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    builder.dry_run = False
    builder.paths.rootfs.mkdir(parents=True)

    rootfs = builder.paths.rootfs.resolve()
    mounts = [
        rootfs / "sys",
        rootfs / "sys/fs/cgroup",
        rootfs / "dev",
        rootfs / "dev/pts",
        Path("/dev/pts"),  # host mount: must never be touched
    ]
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_mounted():  # type: ignore[no-untyped-def]
        active = [path for path in mounts if path != Path("/dev/pts")]
        return tuple(sorted(active, key=lambda path: len(path.parts), reverse=True))

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(command))
        target = Path(command[-1])
        if target in mounts:
            mounts.remove(target)
        return Result()

    monkeypatch.setattr(builder, "_mounted_paths_below_rootfs", fake_mounted)
    monkeypatch.setattr(subprocess, "run", fake_run)
    builder.cleanup_chroot_mounts()

    targets = [Path(call[-1]) for call in calls if call and call[0] == "umount"]
    assert targets.index(rootfs / "sys/fs/cgroup") < targets.index(rootfs / "sys")
    assert targets.index(rootfs / "dev/pts") < targets.index(rootfs / "dev")
    assert Path("/dev/pts") not in targets
    assert all(target.is_relative_to(rootfs) for target in targets)


def test_mountinfo_parser_filters_host_and_sorts_nested_mounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    builder.dry_run = False
    builder.paths.rootfs.mkdir(parents=True)
    rootfs = builder.paths.rootfs.resolve()

    mountinfo = "\n".join([
        f"20 1 0:1 / {rootfs}/sys rw - sysfs sysfs rw",
        f"21 20 0:2 / {rootfs}/sys/fs/cgroup rw - cgroup2 cgroup2 rw",
        f"22 1 0:3 / {rootfs}/dev rw - devtmpfs devtmpfs rw",
        f"23 22 0:4 / {rootfs}/dev/pts rw - devpts devpts rw",
        "24 1 0:5 / /dev/pts rw - devpts devpts rw",
        f"25 1 0:6 / {rootfs}/home rw - tmpfs tmpfs rw",
    ]) + "\n"
    real_read_text = Path.read_text

    def fake_read_text(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(path) == "/proc/self/mountinfo":
            return mountinfo
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    found = builder._mounted_paths_below_rootfs()
    assert found == (
        rootfs / "sys/fs/cgroup",
        rootfs / "dev/pts",
        rootfs / "sys",
        rootfs / "dev",
    )


def test_chroot_rbind_mounts_are_made_rslave() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder._chroot_mounts)
    assert "--make-rslave" in source
    assert '"-l"' not in source
    assert "cleanup_chroot_mounts" in source


def test_installer_tty1_failure_restores_getty_and_autologin_is_scoped() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "getty@tty1.service.d/99-xaac-autologin.conf" in source
    assert "getty@tty{tty}.service.d/99-xaac-authenticated.conf" in source
    assert "ImportCredential=\\n" in source
    assert "ExecStart=-/sbin/agetty -o" in source
    assert "/etc/live/config.conf.d/xaac.conf" in source
    assert "LIVE_CONFIG_CMDLINE" in source
    assert "OnFailure=xaac-installer-restore-getty.service" in source
    assert "ExecStartPre=-/bin/systemctl stop getty@tty1.service" in source
    assert "ExecStart=/bin/systemctl start getty@tty1.service" in source


def test_build_script_has_exit_trap_for_chroot_cleanup() -> None:
    project = Path(__file__).resolve().parents[1]
    script = (project / "scripts/build-production-iso.sh").read_text(encoding="utf-8")
    assert "trap cleanup_chroot_mounts EXIT INT TERM" in script
    assert "--cleanup-mounts-only" in script
