from pathlib import Path
import subprocess
import pytest
from xaac_thin_client_os.kernel_initramfs import (
    KernelInitramfsConfigurator, KernelInitramfsError, create_kernel_initramfs_plan,
)


def config(tmp_path: Path, text: str | None = None) -> Path:
    path = tmp_path / "kernel.yaml"
    path.write_text(text or "kernel_package: linux-image-amd64\ninitramfs_package: initramfs-tools\ncompression: zstd\nmodules: [ext4, mmc_block, ext4]\n", encoding="utf-8")
    return path


def rootfs(tmp_path: Path, *, initrd: bool = False) -> Path:
    root = tmp_path / "rootfs"
    for item in ("etc", "usr/sbin", "lib/modules/6.12.1-amd64", "boot"):
        (root / item).mkdir(parents=True, exist_ok=True)
    (root / "etc/debian_version").write_text("13\n")
    (root / "usr/sbin/update-initramfs").write_text("")
    (root / "boot/vmlinuz-6.12.1-amd64").write_text("")
    if initrd:
        (root / "boot/initrd.img-6.12.1-amd64").write_text("")
    return root


def test_plan_discovers_kernel_and_deduplicates_modules(tmp_path: Path) -> None:
    plan = create_kernel_initramfs_plan(rootfs(tmp_path), config(tmp_path))
    assert plan.kernel_versions == ("6.12.1-amd64",)
    assert plan.modules == ("ext4", "mmc_block")
    assert plan.command_for("6.12.1-amd64")[-3:] == ("-c", "-k", "6.12.1-amd64")


def test_existing_initrd_is_updated(tmp_path: Path) -> None:
    plan = create_kernel_initramfs_plan(rootfs(tmp_path, initrd=True), config(tmp_path))
    assert "-u" in plan.command_for("6.12.1-amd64")

@pytest.mark.parametrize("text,match", [
    ("kernel_package: bad value\ninitramfs_package: initramfs-tools\ncompression: zstd\nmodules: [ext4]\n", "kernel_package"),
    ("kernel_package: linux-image-amd64\ninitramfs_package: initramfs-tools\ncompression: zip\nmodules: [ext4]\n", "compression"),
    ("kernel_package: linux-image-amd64\ninitramfs_package: initramfs-tools\ncompression: zstd\nmodules: []\n", "modules"),
    ("kernel_package: linux-image-amd64\ninitramfs_package: initramfs-tools\ncompression: zstd\nmodules: [bad/name]\n", "Mòdul"),
])
def test_invalid_configuration(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(KernelInitramfsError, match=match):
        create_kernel_initramfs_plan(tmp_path / "rootfs", config(tmp_path, text), allow_missing_versions=True)


def test_missing_kernel_rejected_unless_planning(tmp_path: Path) -> None:
    with pytest.raises(KernelInitramfsError, match="cap kernel"):
        create_kernel_initramfs_plan(tmp_path / "rootfs", config(tmp_path))
    assert create_kernel_initramfs_plan(tmp_path / "rootfs", config(tmp_path), allow_missing_versions=True).kernel_versions == ()


def test_dry_run_is_non_destructive(tmp_path: Path) -> None:
    plan = create_kernel_initramfs_plan(tmp_path / "rootfs", config(tmp_path), allow_missing_versions=True)
    result = KernelInitramfsConfigurator(geteuid=lambda: 1000).execute(plan, tmp_path / "run.log", dry_run=True)
    assert not result.executed
    assert "detect installed kernel" in result.log_path.read_text()


def test_real_execution_writes_configuration_and_validates_initrd(tmp_path: Path) -> None:
    root = rootfs(tmp_path)
    plan = create_kernel_initramfs_plan(root, config(tmp_path))
    def runner(command, **kwargs):
        (root / "boot/initrd.img-6.12.1-amd64").write_text("generated")
        return subprocess.CompletedProcess(command, 0)
    result = KernelInitramfsConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "run.log")
    assert result.executed and result.commands_executed == 1
    assert "mmc_block" in plan.modules_path.read_text()
    assert "COMPRESS=zstd" in plan.configuration_path.read_text()


def test_requires_root(tmp_path: Path) -> None:
    plan = create_kernel_initramfs_plan(rootfs(tmp_path), config(tmp_path))
    with pytest.raises(KernelInitramfsError, match="privilegis"):
        KernelInitramfsConfigurator(geteuid=lambda: 1000).execute(plan, tmp_path / "run.log")


def test_command_failure_is_wrapped(tmp_path: Path) -> None:
    plan = create_kernel_initramfs_plan(rootfs(tmp_path), config(tmp_path))
    def runner(command, **kwargs):
        raise subprocess.CalledProcessError(7, command)
    with pytest.raises(KernelInitramfsError, match="codi 7"):
        KernelInitramfsConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / "run.log")
