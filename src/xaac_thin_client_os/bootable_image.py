"""Assembly of the first complete bootable XAAC disk image."""
from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from xaac_thin_client_os.partitioning import PartitionPlan, create_partition_plan


class BootableImageError(RuntimeError):
    """Raised when a bootable image cannot be planned or assembled safely."""


@dataclass(frozen=True, slots=True)
class BootableImagePlan:
    rootfs: Path
    image_path: Path
    compressed_path: Path
    checksum_path: Path
    mount_dir: Path
    partition_plan: PartitionPlan

    @property
    def size_mib(self) -> int:
        return self.partition_plan.disk_size_mib

    def to_manifest(self) -> dict[str, object]:
        return {
            "image": str(self.image_path),
            "compressed_image": str(self.compressed_path),
            "checksum": str(self.checksum_path),
            "size_mib": self.size_mib,
            "partition_layout": self.partition_plan.to_manifest(),
        }


@dataclass(frozen=True, slots=True)
class BootableImageResult:
    plan: BootableImagePlan
    log_path: Path
    executed: bool
    image_sha256: str | None
    compressed_sha256: str | None
    files_written: tuple[Path, ...]


def create_bootable_image_plan(
    rootfs: Path,
    artifacts_dir: Path,
    temporary_dir: Path,
    partitions_config: Path,
    *,
    project_slug: str = "xaac-thin-client-os",
    allow_incomplete_rootfs: bool = False,
) -> BootableImagePlan:
    resolved_rootfs = rootfs.resolve()
    if resolved_rootfs == Path("/") or not resolved_rootfs.is_dir():
        raise BootableImageError(f"Rootfs inexistent o insegur: {resolved_rootfs}")
    if not project_slug or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in project_slug):
        raise BootableImageError("Nom d'imatge no vàlid")
    required = (
        resolved_rootfs / "etc/debian_version",
        resolved_rootfs / "etc/fstab",
    )
    if not allow_incomplete_rootfs and any(not path.is_file() for path in required):
        raise BootableImageError("El rootfs no està complet: falten Debian o fstab")
    if not allow_incomplete_rootfs:
        kernels = tuple((resolved_rootfs / "boot").glob("vmlinuz-*"))
        initrds = tuple((resolved_rootfs / "boot").glob("initrd.img-*"))
        if not kernels or not initrds:
            raise BootableImageError("El rootfs no conté kernel i initramfs")

    artifacts = artifacts_dir.resolve()
    temporary = temporary_dir.resolve()
    if artifacts == Path("/") or temporary == Path("/"):
        raise BootableImageError("Directori d'artefactes o temporal insegur")
    image_path = artifacts / f"{project_slug}.img"
    mount_dir = temporary / "image-root"
    # The loop device is a planning placeholder; execution substitutes the real loop.
    partition_plan = create_partition_plan(resolved_rootfs, partitions_config, Path("/dev/loop0"))
    return BootableImagePlan(
        rootfs=resolved_rootfs,
        image_path=image_path,
        compressed_path=image_path.with_suffix(".img.gz"),
        checksum_path=image_path.with_suffix(".img.sha256"),
        mount_dir=mount_dir,
        partition_plan=partition_plan,
    )


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class BootableImageBuilder:
    def __init__(
        self,
        *,
        geteuid: Callable[[], int] = os.geteuid,
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self._geteuid = geteuid
        self._runner = runner

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _partition_path(loop_device: Path, number: int) -> Path:
        return Path(f"{loop_device}p{number}")

    def _run(self, command: tuple[str, ...], log: object, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
        try:
            return self._runner(
                command,
                check=True,
                stdout=subprocess.PIPE if capture else log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise BootableImageError(f"Ha fallat {command[0]} amb codi {exc.returncode}") from exc
        except OSError as exc:
            raise BootableImageError(f"No s'ha pogut executar {command[0]}: {exc}") from exc

    def execute(self, plan: BootableImagePlan, log_path: Path, *, dry_run: bool = False) -> BootableImageResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        plan.image_path.parent.mkdir(parents=True, exist_ok=True)
        commands = (
            ("truncate", "-s", f"{plan.size_mib}M", str(plan.image_path)),
            ("losetup", "--find", "--show", "--partscan", str(plan.image_path)),
            ("rsync", "-aHAX", "--numeric-ids", f"{plan.rootfs}/", f"{plan.mount_dir}/"),
            ("grub-install", "--target=x86_64-efi", "--removable", "--no-nvram"),
        )
        if dry_run:
            log_path.write_text("DRY-RUN\n" + "\n".join(" ".join(command) for command in commands) + "\n", encoding="utf-8")
            return BootableImageResult(plan, log_path, False, None, None, ())
        if self._geteuid() != 0:
            raise BootableImageError("La construcció de la imatge requereix privilegis de root")
        if plan.image_path.exists() or plan.compressed_path.exists():
            raise BootableImageError("L'artefacte de destinació ja existeix")

        mounted: list[Path] = []
        loop_device: Path | None = None
        plan.mount_dir.mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("w", encoding="utf-8") as log:
                self._run(commands[0], log)
                result = self._run(commands[1], log, capture=True)
                loop_text = (result.stdout or "").strip()
                if not loop_text.startswith("/dev/loop"):
                    raise BootableImageError("losetup no ha retornat un dispositiu loop vàlid")
                loop_device = Path(loop_text)
                start = plan.partition_plan.alignment_mib
                self._run(("sgdisk", "--zap-all", str(loop_device)), log)
                for item in plan.partition_plan.partitions:
                    end = start + item.size_mib
                    self._run(("sgdisk", f"--new={item.number}:{start}MiB:{end}MiB", f"--typecode={item.number}:{item.type_code}", f"--change-name={item.number}:{item.label}", str(loop_device)), log)
                    start = end
                self._run(("partprobe", str(loop_device)), log)
                for item in plan.partition_plan.partitions:
                    device = str(self._partition_path(loop_device, item.number))
                    command = ("mkfs.vfat", "-F", "32", "-n", item.label, device) if item.filesystem == "vfat" else ("mkfs.ext4", "-F", "-L", item.label, device)
                    self._run(command, log)

                root_spec = next(item for item in plan.partition_plan.partitions if str(item.mountpoint) == "/")
                self._run(("mount", str(self._partition_path(loop_device, root_spec.number)), str(plan.mount_dir)), log)
                mounted.append(plan.mount_dir)
                self._run(commands[2], log)
                for item in plan.partition_plan.partitions:
                    if str(item.mountpoint) == "/":
                        continue
                    destination = plan.mount_dir / str(item.mountpoint).lstrip("/")
                    destination.mkdir(parents=True, exist_ok=True)
                    self._run(("mount", str(self._partition_path(loop_device, item.number)), str(destination)), log)
                    mounted.append(destination)
                self._run(("grub-install", "--target=x86_64-efi", f"--boot-directory={plan.mount_dir / 'boot'}", f"--efi-directory={plan.mount_dir / 'boot/efi'}", "--removable", "--no-nvram"), log)
                self._run(("sync",), log)
        finally:
            for destination in reversed(mounted):
                try:
                    self._runner(("umount", str(destination)), check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
                except OSError:
                    pass
            if loop_device is not None:
                try:
                    self._runner(("losetup", "--detach", str(loop_device)), check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
                except OSError:
                    pass
            shutil.rmtree(plan.mount_dir, ignore_errors=True)

        image_hash = self._sha256(plan.image_path)
        with plan.image_path.open("rb") as source, plan.compressed_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        compressed_hash = self._sha256(plan.compressed_path)
        plan.checksum_path.write_text(
            f"{image_hash}  {plan.image_path.name}\n{compressed_hash}  {plan.compressed_path.name}\n",
            encoding="utf-8",
        )
        files = (plan.image_path, plan.compressed_path, plan.checksum_path)
        return BootableImageResult(plan, log_path, True, image_hash, compressed_hash, files)
