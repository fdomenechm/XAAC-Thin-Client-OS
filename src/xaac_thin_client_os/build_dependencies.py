"""Validation of host tools required to assemble a bootable image."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass


class BuildDependencyError(RuntimeError):
    """Raised when one or more host-side build tools are unavailable."""


@dataclass(frozen=True, slots=True)
class BuildDependencyReport:
    available: tuple[str, ...]
    missing: tuple[str, ...]


REQUIRED_BUILD_COMMANDS: tuple[str, ...] = (
    "debootstrap",
    "truncate",
    "losetup",
    "sgdisk",
    "partprobe",
    "mkfs.vfat",
    "mkfs.ext4",
    "mount",
    "umount",
    "rsync",
    "grub-install",
    "sync",
)

DEBIAN_BUILD_PACKAGES: tuple[str, ...] = (
    "debootstrap",
    "gdisk",
    "parted",
    "dosfstools",
    "e2fsprogs",
    "rsync",
    "grub-efi-amd64-bin",
    "grub2-common",
    "util-linux",
    "coreutils",
)


def inspect_build_dependencies(
    *, search: Callable[[str], str | None] = shutil.which,
) -> BuildDependencyReport:
    available: list[str] = []
    missing: list[str] = []
    for command in REQUIRED_BUILD_COMMANDS:
        (available if search(command) else missing).append(command)
    return BuildDependencyReport(tuple(available), tuple(missing))


def require_build_dependencies(
    *, search: Callable[[str], str | None] = shutil.which,
) -> BuildDependencyReport:
    report = inspect_build_dependencies(search=search)
    if report.missing:
        missing = ", ".join(report.missing)
        packages = " ".join(DEBIAN_BUILD_PACKAGES)
        raise BuildDependencyError(
            "Falten dependències del constructor: "
            f"{missing}. Instal·leu-les amb: sudo apt install {packages}"
        )
    return report
