from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from xaac_thin_client_os.production_builder import (
    BuildPaths,
    BuildSettings,
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
    assert "username=" not in grub
    assert "user-fullname=" not in grub
    assert " components " not in grub
    assert "live-config" not in grub


def test_production_kiosk_account_has_no_interactive_shell() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "--create-home --shell /usr/sbin/nologin --gid xaac-kiosk xaac-kiosk" in source
    assert '["usermod", "--shell", "/usr/sbin/nologin", "xaac-kiosk"]' in source
    assert "--shell /bin/bash --gid xaac-kiosk" not in source

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
    assert "live-config" not in iso
    assert "username:" not in iso
    assert "user_fullname:" not in iso


def test_production_builder_reconfigures_keyboard_noninteractively() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "dpkg-reconfigure keyboard-configuration" in source
    assert "DEBIAN_FRONTEND=noninteractive" in source
    assert 'update-locale", f"LANG={self.settings.locale}' in source


def test_installer_step5_completes_uefi_boot_and_postinstall() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "/usr/local/sbin/xaac-installer-welcome" in source
    assert "ConditionKernelCommandLine=xaac.mode=installer" in source
    assert "Conflicts=getty@tty1.service" in source
    assert "TTYPath=/dev/tty1" in source
    assert "Instal·lador (pas 5)" in source
    assert "ATENCIÓ: aquest pas elimina totes les dades" in source
    assert "minimum_size=7000000000" in source
    assert "INSTALL XAAC" in source
    assert "El disc seleccionat conté el sistema Live actiu" in source
    assert "No s’ha detectat alimentació externa" in source
    assert "sgdisk --zap-all" in source
    assert "-c 1:XAAC_EFI" in source
    assert "-c 2:XAAC_ROOT" in source
    assert "-c 3:XAAC_DATA" in source
    assert "-c 4:XAAC_RECOVERY" in source
    assert "mkfs.vfat -F 32 -n XAAC_EFI" in source
    assert "mkfs.ext4 -F -L XAAC_ROOT" in source
    assert "unsquashfs -f -d" in source
    assert "filesystem.squashfs" in source
    assert 'kernel_version=$(find "$mount_root/lib/modules"' in source
    assert '/run/live/medium/live/vmlinuz' in source
    assert '/run/live/medium/live/initrd.img' in source
    assert 'vmlinuz-$kernel_version' in source
    assert 'initrd.img-$kernel_version' in source
    assert "UUID=$root_uuid / ext4 defaults,noatime 0 1" in source
    assert "trap cleanup_install EXIT HUP INT TERM" in source
    assert "grub-install --target=x86_64-efi" in source
    assert "--removable --no-nvram --recheck" in source
    assert "shimx64.efi.signed" in source
    assert "x86_64-efi-signed/grubx64.efi.signed" in source
    assert "EFI/BOOT/BOOTX64.EFI" in source
    assert "EFI/BOOT/grubx64.efi" in source
    assert "search --no-floppy --fs-uuid --set=root $root_uuid" in source
    assert "No és un executable PE/COFF vàlid" in source
    assert "fsck.vfat -n" in source
    assert "sgdisk -i 1" in source
    assert "update-grub" in source
    assert 'GRUB_DISTRIBUTOR="XAAC Thin Client OS"' in source
    assert "menuentry \'XAAC Thin Client OS\'" in source
    assert 'chmod -x "$mount_root/etc/grub.d/10_linux"' in source
    assert "grub.cfg no conté l’entrada XAAC Thin Client OS" in source
    assert "grub.cfg no conté cap ordre linux" in source
    assert "grub.cfg no conté cap ordre initrd" in source
    assert "etc/machine-id" in source
    assert "ssh_host_*" in source
    assert "first-boot.pending" in source
    assert "installation-summary.txt" in source
    assert "Instal·lació completada i verificada" in source
    assert "Configureu ara la contrasenya" in source
    assert "stty -echo" in source
    assert '${#admin_password}' in source
    assert 'openssl passwd -6 -stdin' in source
    assert 'passwd -S xaac-admin' in source
    assert '/var/lib/xaac/admin/password-changed' in source
    assert 'unset admin_password' in source
    assert '/var/lib/xaac/installation/consolidated' in source
    assert 'L’instal·lador continua present al sistema instal·lat' in source
    assert 'PRETTY_NAME=\\"XAAC Thin Client OS' in source
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


def test_installer_tty1_failure_restores_authenticated_getty_without_autologin() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "getty@tty1.service.d/99-xaac-autologin.conf" not in source
    assert "agetty --autologin xaac-kiosk" not in source
    assert "getty@tty{tty}.service.d/99-xaac-authenticated.conf" in source
    assert "OnFailure=xaac-installer-restore-getty.service" in source
    assert "ExecStartPre=-/bin/systemctl stop getty@tty1.service" in source
    assert "ExecStart=/bin/systemctl start getty@tty1.service" in source

def test_build_script_has_exit_trap_for_chroot_cleanup() -> None:
    project = Path(__file__).resolve().parents[1]
    script = (project / "scripts/build-production-iso.sh").read_text(encoding="utf-8")
    assert "trap cleanup_on_exit EXIT" in script
    assert "trap 'cleanup_on_signal INT' INT" in script
    assert "trap 'cleanup_on_signal TERM' TERM" in script
    assert "--cleanup-mounts-only" in script
    assert 'local status=$?' in script


def test_cleanup_chroot_mounts_retries_transient_busy_mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    builder.dry_run = False
    builder.paths.rootfs.mkdir(parents=True)
    target = builder.paths.rootfs.resolve() / "sys"
    active = True
    attempts = 0

    class Result:
        def __init__(self, returncode: int, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout

    def fake_mounted():  # type: ignore[no-untyped-def]
        return (target,) if active else ()

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal active, attempts
        if command[0] == "sync":
            return Result(0)
        if command[0] == "umount":
            attempts += 1
            if attempts < 3:
                return Result(32, "target is busy")
            active = False
            return Result(0)
        return Result(0)

    monkeypatch.setattr(builder, "_mounted_paths_below_rootfs", fake_mounted)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    builder.cleanup_chroot_mounts()
    assert attempts == 3


def test_cleanup_chroot_mounts_reports_mount_users(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    builder.dry_run = False
    builder.paths.rootfs.mkdir(parents=True)
    target = builder.paths.rootfs.resolve() / "sys"

    class Result:
        returncode = 32
        stdout = "target is busy"

    monkeypatch.setattr(builder, "_mounted_paths_below_rootfs", lambda: (target,))
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(builder, "_mount_users", lambda _target: "PID 1234 apt-get")

    with pytest.raises(ProductionBuildError, match="PID 1234 apt-get"):
        builder.cleanup_chroot_mounts()


def test_production_builder_does_not_require_live_config(project_root: Path) -> None:
    settings = BuildSettings.load(project_root)
    assert "live-boot" in settings.packages
    assert "live-config" not in settings.packages


def test_production_builder_uses_one_appliance_kernel_policy_for_live_and_installed_boot(project_root: Path) -> None:
    settings = BuildSettings.load(project_root)
    params = settings.kernel_parameters
    assert "quiet" in params
    assert "splash" in params
    assert "loglevel=0" in params
    assert "loglevel=3" not in params
    assert "systemd.log_level=emerg" in params
    assert "systemd.show_status=0" in params
    assert "rd.systemd.show_status=0" in params
    assert "vt.global_cursor_default=0" in params
    assert "udev.log_priority=3" in params
    assert "plymouth.ignore-serial-consoles" in params
    assert "intel_idle.max_cstate=1" in params


def test_cleanup_stops_chroot_processes_before_unmounting() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.cleanup_chroot_mounts)
    assert source.index("self._stop_chroot_processes()") < source.index('["umount", str(target)]')


def test_installer_script_with_signed_uefi_fallback_has_valid_shell_syntax(tmp_path: Path) -> None:
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(ProductionIsoBuilder.phase_configure))
    tree = ast.parse(source)
    installer = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        target = ast.get_source_segment(source, node.args[0]) or ""
        if "xaac-installer-welcome" not in target or "service" in target:
            continue
        installer = eval(
            compile(ast.Expression(node.args[1]), "<installer>", "eval"),
            {"installed_kernel_cmdline": "quiet splash loglevel=0"},
        )
        break

    assert isinstance(installer, str)
    script = tmp_path / "xaac-installer-welcome"
    script.write_text(installer, encoding="utf-8")
    subprocess.run(["sh", "-n", str(script)], check=True)


def test_installer_admin_password_is_private_and_kiosk_remains_locked() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "stty -echo" in source
    assert "trap 'stty echo 2>/dev/null || true; exit 130' HUP INT TERM" in source
    assert "openssl passwd -6 -stdin" in source
    assert "passwd -S xaac-admin" in source
    assert "chpasswd --encrypted" in source
    assert "chage -E -1 -I -1 -m 0 xaac-admin" in source
    assert "awk -F:" in source and "$mount_root/etc/shadow" in source
    assert "pamtester login xaac-admin authenticate" in source
    assert "chpasswd --encrypted" in source
    assert '["passwd", "--lock", "xaac-kiosk"]' in source
    assert "installation-summary.txt" in source
    assert "admin_password=$admin_password" not in source
    assert "chpasswd --encrypted" in source
    assert "final_shadow_password" in source
    assert "install-credential-state" in source
    assert "fingerprint=%s" in source


def test_development_diagnostics_is_restricted_and_read_only() -> None:
    import inspect

    from xaac_thin_client_os.production_builder import DEVELOPMENT_DIAGNOSTICS_SCRIPT

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert 'self.settings.channel == "development"' in source
    assert "/usr/local/libexec/xaac/diagnostics" in source
    assert "/etc/sudoers.d/xaac-kiosk-diagnostics" in source
    assert "NOPASSWD: /usr/local/libexec/xaac/diagnostics" in source
    assert "/usr/local/libexec/xaac/diagnostics --pam-test" in source
    assert "ALL=(root) ALL" not in source
    assert "bash" not in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "sh -c" not in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "rm -" not in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "mount " not in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "usermod --password" not in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert 'passwd -S "$account"' in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert 'getent shadow "$account"' in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "pamtester login xaac-admin authenticate" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "${#field}" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "prefix=%s" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "XAAC account lock directives" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "System mode: %s" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "Root UUID: %s" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "ESP UUID: %s" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "[GRUB and UEFI boot state]" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "/boot/grub/grub.cfg" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "BOOTX64.EFI" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "account_report xaac-kiosk" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "account_report xaac-admin" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "display-manager.service" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "getty@tty1.service" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "getty@tty2.service" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "ssh.service" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "xaac-installer-welcome.service" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "[network state]" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "ip -brief address show" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "ip -4 route show" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "IP4.GATEWAY" in DEVELOPMENT_DIAGNOSTICS_SCRIPT
    assert "IP4.DNS" in DEVELOPMENT_DIAGNOSTICS_SCRIPT


def test_development_diagnostics_script_has_valid_shell_syntax(tmp_path: Path) -> None:
    from xaac_thin_client_os.production_builder import DEVELOPMENT_DIAGNOSTICS_SCRIPT

    script = tmp_path / "diagnostics"
    script.write_text(DEVELOPMENT_DIAGNOSTICS_SCRIPT, encoding="utf-8")
    subprocess.run(["sh", "-n", str(script)], check=True)


def test_installer_configures_hostname_and_dhcp() -> None:
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "Hostname [xaac-thin-client]" in source
    assert "install_hostname=xaac-thin-client" in source
    assert "xaac-wired.nmconnection" in source
    assert "match-device=type:ethernet" in source
    assert source.count("method=auto") >= 2


def test_production_builder_applies_definitive_kiosk_stack() -> None:
    import inspect
    from xaac_thin_client_os.production_builder import ProductionIsoBuilder
    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    kiosk_source = inspect.getsource(ProductionIsoBuilder._apply_kiosk_stack)
    assert "create_compositor_plan" in kiosk_source
    assert "create_session_manager_plan" in kiosk_source
    assert "create_thin_client_launcher_plan" in kiosk_source
    assert "create_session_supervisor_plan" in kiosk_source
    assert 'enable", "greetd.service"' in source
    assert 'set-default", "graphical.target"' in source
    assert "ConditionKernelCommandLine=!xaac.mode=installer" in kiosk_source


def test_destructive_clean_refuses_active_chroot_mounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    builder.dry_run = False
    builder.paths.rootfs.mkdir(parents=True)
    mounted = builder.paths.rootfs.resolve() / "dev"
    monkeypatch.setattr(builder, "cleanup_chroot_mounts", lambda: None)
    monkeypatch.setattr(builder, "_mounted_paths_below_rootfs", lambda: (mounted,))

    with pytest.raises(ProductionBuildError, match="Operació insegura"):
        builder.clean()


def test_build_script_uses_private_mount_namespace() -> None:
    project = Path(__file__).resolve().parents[1]
    script = (project / "scripts/build-production-iso.sh").read_text(encoding="utf-8")
    assert "unshare --mount --propagation private" in script
    assert "XAAC_PRIVATE_MOUNT_NS" in script


def test_runtime_apt_install_never_prompts_for_conffiles() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder._install_runtime_packages)
    assert "Dpkg::Options::=--force-confdef" in source
    assert "Dpkg::Options::=--force-confold" in source


def test_kiosk_configuration_is_applied_after_runtime_packages() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    install = source.index("self._install_runtime_packages()")
    kiosk = source.index("self._apply_kiosk_stack()")
    assert install < kiosk

    kiosk_source = inspect.getsource(ProductionIsoBuilder._apply_kiosk_stack)
    assert "SessionManagerConfigurator().execute" in kiosk_source
    assert '10-xaac-mode.conf' in kiosk_source


def test_installed_system_uses_greetd_without_tty1_autologin() -> None:
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "agetty --autologin xaac-kiosk" not in source
    assert 'ln -sfn /dev/null "$mount_root/etc/systemd/system/getty@tty1.service"' in source
    assert 'usermod --shell /usr/sbin/nologin xaac-kiosk' in source
    assert 'systemctl enable greetd.service' in source
    assert 'systemctl set-default graphical.target' in source


def test_production_package_set_always_contains_roboto() -> None:
    import inspect
    from xaac_thin_client_os.production_builder import BuildSettings
    assert '"fonts-roboto"' in inspect.getsource(BuildSettings.load)
    assert '"nano"' in inspect.getsource(BuildSettings.load)


def test_installer_hostname_accepts_uppercase_letters() -> None:
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "*[!A-Za-z0-9-]*" in source


def test_production_builder_requires_real_xaac_thinclient_package(project_root: Path) -> None:
    package = project_root / "packages/xaac-thinclient_1.0.0_all.deb"
    assert package.is_file()
    assert package.read_bytes()[:8] == b"!<arch>\n"
    source = (project_root / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "configure-verify-xaac-thinclient" in source
    assert "command -v xaac-thinclient" in source
    assert "systemctl --global disable xaac-thinclient.service" in source

def test_kiosk_configs_do_not_expose_labwc_menu_or_default_bindings(project_root: Path, tmp_path: Path) -> None:
    from xaac_thin_client_os.compositor import create_compositor_plan
    plan = create_compositor_plan(tmp_path / "rootfs", project_root / "config/compositor.yaml")
    files = {str(path): content for path, content, _ in plan.files}
    rc = files["/etc/xaac/labwc/rc.xml"]
    assert "<menu" not in rc
    assert "<default" not in rc
    assert "<keyboard />" in rc and "<mouse />" in rc
    assert "<policy>center</policy>" in rc
    assert 'name="AutoPlace" policy="center"' in rc


def test_block5_is_verified_in_rootfs_squashfs_and_installed_system() -> None:
    import inspect

    configure = inspect.getsource(ProductionIsoBuilder.phase_configure)
    squashfs = inspect.getsource(ProductionIsoBuilder.phase_squashfs)
    verify = inspect.getsource(ProductionIsoBuilder._verify_thinclient_rootfs)
    assert 'packages/xaac-thinclient_1.0.0_all.deb' in configure
    assert '/etc/xaac/block5-integration' in configure
    assert '/usr/bin/xaac-thinclient' in verify
    assert 'Package: xaac-thinclient' in verify
    assert 'Version: 1.0.0' in verify
    assert 'squashfs-verify-xaac-thinclient' in squashfs
    assert 'squashfs-verify-block5-marker' in squashfs
    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert 'XAAC Thin Client no existeix al sistema instal·lat.' in source
    assert 'xaac-thinclient 1.0.0 no consta instal·lat.' in source


def test_production_build_script_forces_current_checkout_source() -> None:
    script = (Path(__file__).parents[1] / "scripts" / "build-production-iso.sh").read_text()
    assert 'export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"' in script
    assert 'xaac_thin_client_os.production_builder as m' in script
    assert 'EXPECTED_BUILDER_MODULE="$PROJECT_ROOT/src/xaac_thin_client_os/production_builder.py"' in script
    assert 'constructor XAAC diferent del codi font actual' in script


def test_block5_installer_provisions_thinclient_identity_and_rdp() -> None:
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "Servidor RDP (nom DNS o IP)" in source
    assert "Domini RDP:" in source
    assert 'device_name = $install_hostname' in source
    assert 'host = $install_rdp_host' in source
    assert 'domain = $install_rdp_domain' in source
    assert 'enabled = true' in source


def test_block5_thinclient_theme_forces_roboto_and_darker_background() -> None:
    import inspect
    source = inspect.getsource(ProductionIsoBuilder._customize_xaac_thinclient_theme)
    assert 'font-family: "Roboto"' in source
    assert '#dce4ed' in source
    configure = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert 'self._customize_xaac_thinclient_theme()' in configure


def test_production_boot_and_shutdown_use_xaac_plymouth_branding() -> None:
    import inspect

    project = Path(__file__).resolve().parents[1]
    source = inspect.getsource(ProductionIsoBuilder)
    asset = project / "assets/branding/XAAC_TC_OS.png"

    assert asset.is_file()
    assert asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert "- plymouth" in (project / "config/packages.yaml").read_text(encoding="utf-8")
    assert "assets/branding/XAAC_TC_OS.png" in source
    assert "/usr/share/plymouth/themes/xaac" in source
    assert 'ModuleName=script' in source
    assert 'plymouth-set-default-theme", "xaac"' in source
    assert "GRUB_TIMEOUT=0" in source
    assert "GRUB_TIMEOUT_STYLE=hidden" in source
    assert 'kernel_cmdline = " ".join(self.settings.kernel_parameters)' in source
    assert 'installed_kernel_cmdline = " ".join(self.settings.kernel_parameters)' in source
    assert 'GRUB_CMDLINE_LINUX_DEFAULT="{kernel_cmdline}"' in source
    assert "boot-verify-xaac-plymouth" in source
    assert "lsinitramfs" in source
    assert "/etc/systemd/system/xaac-clear-console-before-shutdown.service" in source
    assert "DefaultDependencies=no" in source
    assert "Before=plymouth-poweroff.service plymouth-reboot.service plymouth-halt.service" in source
    assert "systemd-poweroff.service systemd-reboot.service systemd-halt.service" in source
    assert "WantedBy=poweroff.target reboot.target halt.target" in source
    assert "/dev/tty1" in source
    assert '"systemctl", "enable", "xaac-clear-console-before-shutdown.service"' in source


def test_production_iso_hides_grub_menu_and_uses_appliance_boot_parameters(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    from types import SimpleNamespace
    builder.settings = SimpleNamespace(
        output_name="xaac.iso",
        kernel_parameters=("quiet", "splash", "loglevel=0", "systemd.show_status=0"),
        volume_id="XAAC_TC_OS",
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
    assert "set timeout_style=hidden" in grub
    assert "set timeout=2" in grub
    installer_line = next(line for line in grub.splitlines() if "xaac.mode=installer" in line)
    assert "boot=live quiet splash loglevel=0 systemd.show_status=0" in installer_line
    assert installer_line.count(" quiet") == 1


def test_uefi_defaults_match_silent_graphical_boot_policy() -> None:
    project = Path(__file__).resolve().parents[1]
    uefi = (project / "config/uefi.yaml").read_text(encoding="utf-8")
    packages = (project / "config/packages.yaml").read_text(encoding="utf-8")

    assert "timeout_seconds: 0" in uefi
    for parameter in (
        "splash",
        "loglevel=0",
        "systemd.log_level=emerg",
        "systemd.show_status=0",
        "rd.systemd.show_status=0",
        "vt.global_cursor_default=0",
        "udev.log_priority=3",
        "plymouth.ignore-serial-consoles",
    ):
        assert f"  - {parameter}" in uefi
    assert "- plymouth" in packages


def test_production_builder_installs_persistent_freerdp_certificate_store() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder._configure_freerdp_certificate_store)
    assert "/usr/lib/tmpfiles.d/xaac-freerdp.conf" in source
    assert "d /etc/xaac/freerdp 0700 xaac-kiosk xaac-kiosk -" in source
    assert "d /etc/xaac/freerdp/server 0700 xaac-kiosk xaac-kiosk -" in source
    assert '"/usr/bin/install", "-d", "-m", "0700"' in source
    assert '"-o", "xaac-kiosk", "-g", "xaac-kiosk"' in source


def test_production_configure_calls_freerdp_store_after_kiosk_account_creation() -> None:
    import inspect

    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    user_pos = source.index("configure-user-kiosk")
    store_pos = source.index("self._configure_freerdp_certificate_store()")
    package_pos = source.index("if debs:")
    assert user_pos < store_pos < package_pos


def test_production_builder_requires_real_xaac_agent_package(project_root: Path) -> None:
    import inspect

    package = project_root / "packages/xaac-agent_1.0.0-8_amd64.deb"
    assert package.is_file()
    assert package.stat().st_size > 1024
    assert package.read_bytes()[:8] == b"!<arch>\n"
    source = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "agent_debian_version = self._validate_xaac_agent_artifact()" in source
    assert "configure-verify-xaac-agent" in source
    assert "agent_debian_version" in source
    assert "/opt/xaac-agent/runtime/bin/python3.13" in source
    assert "/usr/sbin/xaac-agent-admin" in source
    assert "xaac-enrollment-token:-/etc/xaac-agent/enrollment.token" in source
    assert "configure-xaac-xms-enrollment" in source
    assert "configure-xaac-ipc-membership" in source
    assert "grep -Fx 'ReadWritePaths=/etc/xaac'" in source
    assert "! grep -F 'CAP_SYS_ADMIN'" in source


def test_agent_preflight_accepts_current_canonical_release_provenance(project_root: Path) -> None:
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(project_root)  # type: ignore[misc]
    assert builder._validate_xaac_agent_artifact() == "1.0.0-8"
