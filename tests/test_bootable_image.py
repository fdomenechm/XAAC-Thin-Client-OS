from pathlib import Path
import subprocess
import pytest

from xaac_thin_client_os.bootable_image import (
    BootableImageBuilder, BootableImageError, create_bootable_image_plan,
)


def prepared_rootfs(tmp_path: Path) -> Path:
    rootfs = tmp_path / "run/rootfs"
    (rootfs / "etc").mkdir(parents=True)
    (rootfs / "boot").mkdir()
    (rootfs / "etc/debian_version").write_text("13\n")
    (rootfs / "etc/fstab").write_text("# fstab\n")
    (rootfs / "boot/vmlinuz-test").write_text("kernel")
    (rootfs / "boot/initrd.img-test").write_text("initrd")
    return rootfs


def plan(tmp_path: Path, *, incomplete: bool = False):
    rootfs = tmp_path / "run/rootfs" if incomplete else prepared_rootfs(tmp_path)
    rootfs.mkdir(parents=True, exist_ok=True)
    return create_bootable_image_plan(
        rootfs, tmp_path / "run/artifacts", tmp_path / "run/tmp",
        Path("config/partitions.yaml"), allow_incomplete_rootfs=incomplete,
    )


def test_plan_uses_configured_size_and_artifacts(tmp_path: Path) -> None:
    value = plan(tmp_path)
    assert value.size_mib == 7168
    assert value.image_path.name == "xaac-thin-client-os.img"
    assert value.compressed_path.name.endswith(".img.gz")
    assert len(value.partition_plan.partitions) == 4


def test_plan_manifest_is_auditable(tmp_path: Path) -> None:
    manifest = plan(tmp_path).to_manifest()
    assert manifest["size_mib"] == 7168
    assert manifest["partition_layout"]["partitions"][0]["label"] == "XAAC_EFI"


def test_dry_run_is_unprivileged_and_non_destructive(tmp_path: Path) -> None:
    value = plan(tmp_path)
    result = BootableImageBuilder(geteuid=lambda: 1000).execute(value, tmp_path / "image.log", dry_run=True)
    assert not result.executed
    assert not value.image_path.exists()
    assert "losetup" in result.log_path.read_text()


def test_real_build_requires_root(tmp_path: Path) -> None:
    with pytest.raises(BootableImageError, match="privilegis"):
        BootableImageBuilder(geteuid=lambda: 1000).execute(plan(tmp_path), tmp_path / "log")


def test_rejects_existing_artifact(tmp_path: Path) -> None:
    value = plan(tmp_path)
    value.image_path.parent.mkdir(parents=True)
    value.image_path.write_bytes(b"old")
    with pytest.raises(BootableImageError, match="ja existeix"):
        BootableImageBuilder(geteuid=lambda: 0).execute(value, tmp_path / "log")


def test_rejects_incomplete_rootfs(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"; rootfs.mkdir()
    with pytest.raises(BootableImageError, match="no està complet"):
        create_bootable_image_plan(rootfs, tmp_path / "a", tmp_path / "t", Path("config/partitions.yaml"))


def test_rejects_missing_kernel(tmp_path: Path) -> None:
    rootfs = prepared_rootfs(tmp_path)
    (rootfs / "boot/vmlinuz-test").unlink()
    with pytest.raises(BootableImageError, match="kernel"):
        create_bootable_image_plan(rootfs, tmp_path / "a", tmp_path / "t", Path("config/partitions.yaml"))


def test_rejects_unsafe_slug(tmp_path: Path) -> None:
    with pytest.raises(BootableImageError, match="Nom"):
        create_bootable_image_plan(prepared_rootfs(tmp_path), tmp_path / "a", tmp_path / "t", Path("config/partitions.yaml"), project_slug="../bad")


def test_rejects_unsafe_or_missing_rootfs(tmp_path: Path) -> None:
    with pytest.raises(BootableImageError, match="Rootfs"):
        create_bootable_image_plan(tmp_path / "missing", tmp_path / "a", tmp_path / "t", Path("config/partitions.yaml"))


def test_partition_path_for_loop_device() -> None:
    assert BootableImageBuilder._partition_path(Path("/dev/loop7"), 3) == Path("/dev/loop7p3")


def test_command_failure_is_wrapped(tmp_path: Path) -> None:
    value = plan(tmp_path)
    def runner(command, **kwargs):
        raise subprocess.CalledProcessError(9, command)
    with pytest.raises(BootableImageError, match="codi 9"):
        BootableImageBuilder(geteuid=lambda: 0, runner=runner).execute(value, tmp_path / "log")


def test_oserror_is_wrapped(tmp_path: Path) -> None:
    value = plan(tmp_path)
    def runner(command, **kwargs):
        raise OSError("missing")
    with pytest.raises(BootableImageError, match="No s'ha pogut"):
        BootableImageBuilder(geteuid=lambda: 0, runner=runner).execute(value, tmp_path / "log")


def test_invalid_loop_output_is_rejected(tmp_path: Path) -> None:
    value = plan(tmp_path)
    calls = 0
    def runner(command, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 0, stdout="bad\n" if calls == 2 else "")
    with pytest.raises(BootableImageError, match="loop vàlid"):
        BootableImageBuilder(geteuid=lambda: 0, runner=runner).execute(value, tmp_path / "log")


def test_successful_simulated_build_creates_hashes_and_cleans_up(tmp_path: Path) -> None:
    from dataclasses import replace
    value = plan(tmp_path)
    value = replace(value, partition_plan=replace(value.partition_plan, disk_size_mib=1))
    calls: list[tuple[str, ...]] = []
    def runner(command, **kwargs):
        command = tuple(command)
        calls.append(command)
        if command[0] == "truncate":
            value.image_path.write_bytes(b"XAAC image payload\n")
        if command[:2] == ("losetup", "--find"):
            return subprocess.CompletedProcess(command, 0, stdout="/dev/loop7\n")
        return subprocess.CompletedProcess(command, 0, stdout="")
    result = BootableImageBuilder(geteuid=lambda: 0, runner=runner).execute(value, tmp_path / "image.log")
    assert result.executed
    assert result.image_sha256 and len(result.image_sha256) == 64
    assert result.compressed_sha256 and len(result.compressed_sha256) == 64
    assert value.compressed_path.is_file()
    assert value.checksum_path.read_text().count("\n") == 2
    assert ("losetup", "--detach", "/dev/loop7") in calls
    assert not value.mount_dir.exists()


def test_sha256_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "sample"; path.write_bytes(b"abc")
    assert BootableImageBuilder._sha256(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
