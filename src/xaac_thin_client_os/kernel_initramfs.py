"""Kernel and initramfs configuration for a Debian root filesystem."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml


class KernelInitramfsError(RuntimeError):
    """Raised when kernel/initramfs configuration is invalid or fails."""


_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
_MODULE = re.compile(r"^[A-Za-z0-9_+-]+$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+:~_-]*$")


@dataclass(frozen=True, slots=True)
class KernelInitramfsPlan:
    rootfs: Path
    kernel_package: str
    initramfs_package: str
    compression: str
    modules: tuple[str, ...]
    kernel_versions: tuple[str, ...]

    @property
    def modules_path(self) -> Path:
        return self.rootfs / "etc/initramfs-tools/modules"

    @property
    def configuration_path(self) -> Path:
        return self.rootfs / "etc/initramfs-tools/conf.d/xaac"

    def command_for(self, version: str) -> tuple[str, ...]:
        mode = "-u" if (self.rootfs / f"boot/initrd.img-{version}").is_file() else "-c"
        return ("chroot", str(self.rootfs), "update-initramfs", mode, "-k", version)

    def to_manifest(self) -> dict[str, object]:
        return {
            "kernel_package": self.kernel_package,
            "initramfs_package": self.initramfs_package,
            "compression": self.compression,
            "modules": list(self.modules),
            "kernel_versions": list(self.kernel_versions),
            "commands": [list(self.command_for(version)) for version in self.kernel_versions],
        }


@dataclass(frozen=True, slots=True)
class KernelInitramfsResult:
    plan: KernelInitramfsPlan
    log_path: Path
    executed: bool
    files_written: tuple[Path, ...]
    commands_executed: int


def _load_mapping(path: Path) -> dict[str, object]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KernelInitramfsError(f"No es pot llegir {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise KernelInitramfsError("La configuració del kernel ha de ser un mapa YAML")
    allowed = {"kernel_package", "initramfs_package", "compression", "modules"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise KernelInitramfsError("Claus desconegudes: " + ", ".join(unknown))
    return payload


def _discover_versions(rootfs: Path) -> tuple[str, ...]:
    modules_dir = rootfs / "lib/modules"
    if not modules_dir.is_dir():
        return ()
    versions = []
    for path in modules_dir.iterdir():
        if path.is_dir() and _VERSION.fullmatch(path.name):
            versions.append(path.name)
    return tuple(sorted(set(versions)))


def create_kernel_initramfs_plan(
    rootfs: Path, config_path: Path, *, allow_missing_versions: bool = False
) -> KernelInitramfsPlan:
    resolved = rootfs.resolve()
    if resolved == Path("/") or resolved.parent == Path("/"):
        raise KernelInitramfsError(f"Rootfs insegur: {resolved}")
    payload = _load_mapping(config_path)
    kernel_package = payload.get("kernel_package")
    initramfs_package = payload.get("initramfs_package")
    compression = payload.get("compression")
    modules = payload.get("modules")
    if not isinstance(kernel_package, str) or not _NAME.fullmatch(kernel_package):
        raise KernelInitramfsError("kernel_package no és vàlid")
    if not isinstance(initramfs_package, str) or not _NAME.fullmatch(initramfs_package):
        raise KernelInitramfsError("initramfs_package no és vàlid")
    if compression not in {"gzip", "lz4", "zstd"}:
        raise KernelInitramfsError("compression ha de ser gzip, lz4 o zstd")
    if not isinstance(modules, list) or not modules:
        raise KernelInitramfsError("modules ha de ser una llista no buida")
    normalized: list[str] = []
    for module in modules:
        if not isinstance(module, str) or not _MODULE.fullmatch(module):
            raise KernelInitramfsError(f"Mòdul no vàlid: {module!r}")
        normalized.append(module)
    versions = _discover_versions(resolved)
    if not versions and not allow_missing_versions:
        raise KernelInitramfsError("No s'ha detectat cap kernel instal·lat en /lib/modules")
    return KernelInitramfsPlan(
        resolved,
        kernel_package,
        initramfs_package,
        str(compression),
        tuple(sorted(set(normalized))),
        versions,
    )


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class KernelInitramfsConfigurator:
    def __init__(self, *, geteuid: Callable[[], int] = os.geteuid, runner: CommandRunner = subprocess.run) -> None:
        self._geteuid = geteuid
        self._runner = runner

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise KernelInitramfsError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o644)
        temporary.replace(path)

    @staticmethod
    def _validate_rootfs(plan: KernelInitramfsPlan) -> None:
        required = (
            plan.rootfs / "etc/debian_version",
            plan.rootfs / "usr/sbin/update-initramfs",
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise KernelInitramfsError("El rootfs no està preparat; falten: " + ", ".join(missing))
        for version in plan.kernel_versions:
            if not (plan.rootfs / f"boot/vmlinuz-{version}").is_file():
                raise KernelInitramfsError(f"Falta la imatge del kernel {version}")

    def execute(self, plan: KernelInitramfsPlan, log_path: Path, *, dry_run: bool = False) -> KernelInitramfsResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        commands = tuple(plan.command_for(version) for version in plan.kernel_versions)
        modules_content = "# XAAC Thin Client OS - required early boot modules\n" + "\n".join(plan.modules) + "\n"
        config_content = f"COMPRESS={plan.compression}\nMODULES=most\n"
        if dry_run:
            log_path.write_text(
                "DRY-RUN\n"
                + f"write {plan.modules_path}\nwrite {plan.configuration_path}\n"
                + ("\n".join(" ".join(command) for command in commands) or "detect installed kernel versions at execution time")
                + "\n",
                encoding="utf-8",
            )
            return KernelInitramfsResult(plan, log_path, False, (), 0)
        if self._geteuid() != 0:
            raise KernelInitramfsError("La generació de l'initramfs requereix privilegis de root")
        self._validate_rootfs(plan)
        self._write_atomic(plan.modules_path, modules_content)
        self._write_atomic(plan.configuration_path, config_content)
        with log_path.open("w", encoding="utf-8") as log_file:
            for command in commands:
                log_file.write(f"$ {' '.join(command)}\n")
                log_file.flush()
                try:
                    self._runner(command, check=True, stdout=log_file, stderr=subprocess.STDOUT, text=True)
                except subprocess.CalledProcessError as exc:
                    raise KernelInitramfsError(
                        f"Ha fallat update-initramfs amb codi {exc.returncode}; consulteu {log_path}"
                    ) from exc
                except OSError as exc:
                    raise KernelInitramfsError(f"No s'ha pogut executar chroot: {exc}") from exc
        for version in plan.kernel_versions:
            if not (plan.rootfs / f"boot/initrd.img-{version}").is_file():
                raise KernelInitramfsError(f"No s'ha generat initrd.img-{version}")
        return KernelInitramfsResult(
            plan, log_path, True, (plan.modules_path, plan.configuration_path), len(commands)
        )
