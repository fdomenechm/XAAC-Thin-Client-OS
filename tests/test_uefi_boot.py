from pathlib import Path
import subprocess
import pytest

from xaac_thin_client_os.uefi_boot import (
    UefiBootConfigurator,
    UefiBootError,
    create_uefi_boot_plan,
)


def config(tmp_path: Path, text: str | None = None) -> Path:
    path = tmp_path / "uefi.yaml"
    path.write_text(text or """target: x86_64-efi
bootloader_id: XAAC
boot_directory: /boot
efi_directory: /boot/efi
timeout_seconds: 1
hidden_menu: true
removable_fallback: true
kernel_parameters: [quiet, loglevel=3, quiet]
""", encoding="utf-8")
    return path


def rootfs(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    for item in ("etc", "usr/sbin", "boot"):
        (root / item).mkdir(parents=True, exist_ok=True)
    (root / "etc/debian_version").write_text("13\n")
    (root / "usr/sbin/grub-install").write_text("")
    (root / "usr/sbin/update-grub").write_text("")
    (root / "boot/vmlinuz-6.12.1-amd64").write_text("")
    (root / "boot/initrd.img-6.12.1-amd64").write_text("")
    return root


def test_plan_is_deterministic_and_uses_removable_fallback(tmp_path: Path) -> None:
    plan = create_uefi_boot_plan(rootfs(tmp_path), config(tmp_path))
    assert plan.kernel_versions == ("6.12.1-amd64",)
    assert plan.kernel_parameters == ("quiet", "loglevel=3")
    assert "--no-nvram" in plan.grub_install_command
    assert "--removable" in plan.grub_install_command
    assert plan.update_grub_command[-1] == "update-grub"


@pytest.mark.parametrize("text,match", [
    ("target: i386-efi\nbootloader_id: XAAC\nboot_directory: /boot\nefi_directory: /boot/efi\ntimeout_seconds: 1\nhidden_menu: true\nremovable_fallback: true\nkernel_parameters: []\n", "target"),
    ("target: x86_64-efi\nbootloader_id: 'bad id'\nboot_directory: /boot\nefi_directory: /boot/efi\ntimeout_seconds: 1\nhidden_menu: true\nremovable_fallback: true\nkernel_parameters: []\n", "bootloader_id"),
    ("target: x86_64-efi\nbootloader_id: XAAC\nboot_directory: ../boot\nefi_directory: /boot/efi\ntimeout_seconds: 1\nhidden_menu: true\nremovable_fallback: true\nkernel_parameters: []\n", "boot_directory"),
    ("target: x86_64-efi\nbootloader_id: XAAC\nboot_directory: /boot\nefi_directory: /boot/efi\ntimeout_seconds: 11\nhidden_menu: true\nremovable_fallback: true\nkernel_parameters: []\n", "timeout_seconds"),
    ("target: x86_64-efi\nbootloader_id: XAAC\nboot_directory: /boot\nefi_directory: /boot/efi\ntimeout_seconds: 1\nhidden_menu: 1\nremovable_fallback: true\nkernel_parameters: []\n", "booleans"),
    ("target: x86_64-efi\nbootloader_id: XAAC\nboot_directory: /boot\nefi_directory: /boot/efi\ntimeout_seconds: 1\nhidden_menu: true\nremovable_fallback: true\nkernel_parameters: ['--bad']\n", "Paràmetre"),
])
def test_invalid_configuration(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(UefiBootError, match=match):
        create_uefi_boot_plan(tmp_path / "rootfs", config(tmp_path, text), allow_missing_kernel=True)


def test_missing_kernel_rejected_unless_dry_run_planning(tmp_path: Path) -> None:
    with pytest.raises(UefiBootError, match="kernel/initramfs"):
        create_uefi_boot_plan(tmp_path / "rootfs", config(tmp_path))
    assert create_uefi_boot_plan(
        tmp_path / "rootfs", config(tmp_path), allow_missing_kernel=True
    ).kernel_versions == ()


def test_dry_run_is_non_destructive(tmp_path: Path) -> None:
    plan = create_uefi_boot_plan(tmp_path / "rootfs", config(tmp_path), allow_missing_kernel=True)
    result = UefiBootConfigurator(geteuid=lambda: 1000).execute(
        plan, tmp_path / "uefi.log", dry_run=True
    )
    assert not result.executed
    assert not plan.defaults_path.exists()
    assert "grub-install" in result.log_path.read_text()


def test_real_execution_generates_boot_files(tmp_path: Path) -> None:
    root = rootfs(tmp_path)
    plan = create_uefi_boot_plan(root, config(tmp_path))

    def runner(command, **kwargs):
        if "grub-install" in command:
            fallback = root / "boot/efi/EFI/BOOT/BOOTX64.EFI"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            fallback.write_text("efi")
        if "update-grub" in command:
            cfg = root / "boot/grub/grub.cfg"
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text("menuentry XAAC")
        return subprocess.CompletedProcess(command, 0)

    result = UefiBootConfigurator(geteuid=lambda: 0, runner=runner).execute(
        plan, tmp_path / "uefi.log"
    )
    assert result.executed and result.commands_executed == 2
    defaults = plan.defaults_path.read_text()
    assert "GRUB_TIMEOUT_STYLE=hidden" in defaults
    assert 'GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=3"' in defaults


def test_requires_root(tmp_path: Path) -> None:
    plan = create_uefi_boot_plan(rootfs(tmp_path), config(tmp_path))
    with pytest.raises(UefiBootError, match="privilegis"):
        UefiBootConfigurator(geteuid=lambda: 1000).execute(plan, tmp_path / "uefi.log")


def test_command_failure_is_wrapped(tmp_path: Path) -> None:
    plan = create_uefi_boot_plan(rootfs(tmp_path), config(tmp_path))
    def runner(command, **kwargs):
        raise subprocess.CalledProcessError(9, command)
    with pytest.raises(UefiBootError, match="codi 9"):
        UefiBootConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "uefi.log")


def test_missing_fallback_is_rejected(tmp_path: Path) -> None:
    root = rootfs(tmp_path)
    plan = create_uefi_boot_plan(root, config(tmp_path))
    def runner(command, **kwargs):
        if "update-grub" in command:
            cfg = root / "boot/grub/grub.cfg"
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text("ok")
        return subprocess.CompletedProcess(command, 0)
    with pytest.raises(UefiBootError, match="BOOTX64.EFI"):
        UefiBootConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "uefi.log")


def test_rejects_unknown_keys_and_non_mapping(tmp_path: Path) -> None:
    with pytest.raises(UefiBootError, match="Claus desconegudes"):
        create_uefi_boot_plan(
            tmp_path / "rootfs",
            config(tmp_path, "unknown: true\n"),
            allow_missing_kernel=True,
        )
    with pytest.raises(UefiBootError, match="mapa YAML"):
        create_uefi_boot_plan(
            tmp_path / "rootfs", config(tmp_path, "- invalid\n"), allow_missing_kernel=True
        )


def test_rejects_missing_or_invalid_parameter_list(tmp_path: Path) -> None:
    text = """target: x86_64-efi
bootloader_id: XAAC
boot_directory: /boot
efi_directory: /boot/efi
timeout_seconds: 1
hidden_menu: true
removable_fallback: true
kernel_parameters: quiet
"""
    with pytest.raises(UefiBootError, match="kernel_parameters"):
        create_uefi_boot_plan(tmp_path / "rootfs", config(tmp_path, text), allow_missing_kernel=True)


def test_rejects_unprepared_rootfs_and_symlinked_efi(tmp_path: Path) -> None:
    root = rootfs(tmp_path)
    (root / "usr/sbin/grub-install").unlink()
    plan = create_uefi_boot_plan(root, config(tmp_path))
    with pytest.raises(UefiBootError, match="falten"):
        UefiBootConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "uefi.log")

    root = rootfs(tmp_path / "second")
    (root / "boot/efi").parent.mkdir(parents=True, exist_ok=True)
    (root / "boot/efi").symlink_to(tmp_path)
    plan = create_uefi_boot_plan(root, config(tmp_path / "second"))
    with pytest.raises(UefiBootError, match="enllaç simbòlic"):
        UefiBootConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "uefi2.log")


def test_oserror_is_wrapped(tmp_path: Path) -> None:
    plan = create_uefi_boot_plan(rootfs(tmp_path), config(tmp_path))
    def runner(command, **kwargs):
        raise OSError("missing chroot")
    with pytest.raises(UefiBootError, match="executar chroot"):
        UefiBootConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "uefi.log")


def test_missing_grub_cfg_is_rejected(tmp_path: Path) -> None:
    root = rootfs(tmp_path)
    plan = create_uefi_boot_plan(root, config(tmp_path))
    def runner(command, **kwargs):
        if "grub-install" in command:
            fallback = root / "boot/efi/EFI/BOOT/BOOTX64.EFI"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            fallback.write_text("efi")
        return subprocess.CompletedProcess(command, 0)
    with pytest.raises(UefiBootError, match="grub.cfg"):
        UefiBootConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "uefi.log")


def test_manifest_contains_complete_uefi_plan(tmp_path: Path) -> None:
    plan = create_uefi_boot_plan(rootfs(tmp_path), config(tmp_path))
    manifest = plan.to_manifest()
    assert manifest["target"] == "x86_64-efi"
    assert manifest["efi_directory"] == "/boot/efi"
    assert len(manifest["commands"]) == 2
