"""UEFI bootloader preparation for a Debian root filesystem."""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml


class UefiBootError(RuntimeError):
    """Raised when UEFI bootloader configuration is invalid or fails."""


_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")
_PARAM = re.compile(r"^[A-Za-z0-9_.=:/,+-]+$")


@dataclass(frozen=True, slots=True)
class UefiBootPlan:
    rootfs: Path
    target: str
    bootloader_id: str
    boot_directory: PurePosixPath
    efi_directory: PurePosixPath
    timeout_seconds: int
    hidden_menu: bool
    removable_fallback: bool
    kernel_parameters: tuple[str, ...]
    kernel_versions: tuple[str, ...]

    @property
    def defaults_path(self) -> Path:
        return self.rootfs / "etc/default/grub.d/20-xaac.cfg"

    @property
    def host_efi_directory(self) -> Path:
        return self.rootfs / self.efi_directory.relative_to("/")

    @property
    def grub_install_command(self) -> tuple[str, ...]:
        command = [
            "chroot", str(self.rootfs), "grub-install",
            f"--target={self.target}", f"--efi-directory={self.efi_directory}",
            f"--boot-directory={self.boot_directory}", f"--bootloader-id={self.bootloader_id}",
            "--no-nvram",
        ]
        if self.removable_fallback:
            command.append("--removable")
        return tuple(command)

    @property
    def update_grub_command(self) -> tuple[str, ...]:
        return ("chroot", str(self.rootfs), "update-grub")

    def to_manifest(self) -> dict[str, object]:
        return {
            "target": self.target,
            "bootloader_id": self.bootloader_id,
            "boot_directory": str(self.boot_directory),
            "efi_directory": str(self.efi_directory),
            "timeout_seconds": self.timeout_seconds,
            "hidden_menu": self.hidden_menu,
            "removable_fallback": self.removable_fallback,
            "kernel_parameters": list(self.kernel_parameters),
            "kernel_versions": list(self.kernel_versions),
            "commands": [list(self.grub_install_command), list(self.update_grub_command)],
        }


@dataclass(frozen=True, slots=True)
class UefiBootResult:
    plan: UefiBootPlan
    log_path: Path
    executed: bool
    files_written: tuple[Path, ...]
    commands_executed: int


def _absolute_directory(value: object, name: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise UefiBootError(f"{name} ha de ser una ruta absoluta")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or path == PurePosixPath("/"):
        raise UefiBootError(f"{name} no és una ruta segura")
    return path


def _load(path: Path) -> dict[str, object]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UefiBootError(f"No es pot llegir {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise UefiBootError("La configuració UEFI ha de ser un mapa YAML")
    allowed = {"target", "bootloader_id", "boot_directory", "efi_directory", "timeout_seconds", "hidden_menu", "removable_fallback", "kernel_parameters"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise UefiBootError("Claus desconegudes: " + ", ".join(unknown))
    return payload


def _kernel_versions(rootfs: Path) -> tuple[str, ...]:
    boot = rootfs / "boot"
    if not boot.is_dir():
        return ()
    versions = []
    for kernel in boot.glob("vmlinuz-*"):
        version = kernel.name.removeprefix("vmlinuz-")
        if version and (boot / f"initrd.img-{version}").is_file():
            versions.append(version)
    return tuple(sorted(set(versions)))


def create_uefi_boot_plan(rootfs: Path, config_path: Path, *, allow_missing_kernel: bool = False) -> UefiBootPlan:
    resolved = rootfs.resolve()
    if resolved == Path("/") or resolved.parent == Path("/"):
        raise UefiBootError(f"Rootfs insegur: {resolved}")
    payload = _load(config_path)
    target = payload.get("target")
    bootloader_id = payload.get("bootloader_id")
    timeout = payload.get("timeout_seconds")
    if target != "x86_64-efi":
        raise UefiBootError("target ha de ser x86_64-efi")
    if not isinstance(bootloader_id, str) or not _TOKEN.fullmatch(bootloader_id):
        raise UefiBootError("bootloader_id no és vàlid")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 0 <= timeout <= 10:
        raise UefiBootError("timeout_seconds ha d'estar entre 0 i 10")
    hidden = payload.get("hidden_menu")
    removable = payload.get("removable_fallback")
    if not isinstance(hidden, bool) or not isinstance(removable, bool):
        raise UefiBootError("hidden_menu i removable_fallback han de ser booleans")
    params = payload.get("kernel_parameters")
    if not isinstance(params, list):
        raise UefiBootError("kernel_parameters ha de ser una llista")
    normalized = []
    for param in params:
        if not isinstance(param, str) or not _PARAM.fullmatch(param) or param.startswith("-"):
            raise UefiBootError(f"Paràmetre del kernel no vàlid: {param!r}")
        normalized.append(param)
    versions = _kernel_versions(resolved)
    if not versions and not allow_missing_kernel:
        raise UefiBootError("No hi ha cap parella kernel/initramfs coherent en /boot")
    return UefiBootPlan(
        resolved, target, bootloader_id,
        _absolute_directory(payload.get("boot_directory"), "boot_directory"),
        _absolute_directory(payload.get("efi_directory"), "efi_directory"),
        timeout, hidden, removable, tuple(dict.fromkeys(normalized)), versions,
    )


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class UefiBootConfigurator:
    def __init__(self, *, geteuid: Callable[[], int] = os.geteuid, runner: CommandRunner = subprocess.run) -> None:
        self._geteuid = geteuid
        self._runner = runner

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise UefiBootError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o644)
        temporary.replace(path)

    @staticmethod
    def _validate_rootfs(plan: UefiBootPlan) -> None:
        required = (
            plan.rootfs / "etc/debian_version",
            plan.rootfs / "usr/sbin/grub-install",
            plan.rootfs / "usr/sbin/update-grub",
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise UefiBootError("El rootfs no està preparat; falten: " + ", ".join(missing))
        if plan.host_efi_directory.is_symlink():
            raise UefiBootError("El directori EFI no pot ser un enllaç simbòlic")

    def execute(self, plan: UefiBootPlan, log_path: Path, *, dry_run: bool = False) -> UefiBootResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "# XAAC Thin Client OS - GRUB UEFI\n"
            f"GRUB_TIMEOUT={plan.timeout_seconds}\n"
            f"GRUB_TIMEOUT_STYLE={'hidden' if plan.hidden_menu else 'menu'}\n"
            'GRUB_DISABLE_OS_PROBER=true\n'
            'GRUB_DISABLE_RECOVERY=true\n'
            'GRUB_CMDLINE_LINUX_DEFAULT="' + ' '.join(plan.kernel_parameters) + '"\n'
        )
        commands = (plan.grub_install_command, plan.update_grub_command)
        if dry_run:
            log_path.write_text("DRY-RUN\n" + f"write {plan.defaults_path}\nmkdir {plan.host_efi_directory}\n" + "\n".join(" ".join(c) for c in commands) + "\n", encoding="utf-8")
            return UefiBootResult(plan, log_path, False, (), 0)
        if self._geteuid() != 0:
            raise UefiBootError("La instal·lació UEFI requereix privilegis de root")
        self._validate_rootfs(plan)
        plan.host_efi_directory.mkdir(parents=True, exist_ok=True)
        self._write_atomic(plan.defaults_path, content)
        with log_path.open("w", encoding="utf-8") as log:
            for command in commands:
                log.write(f"$ {' '.join(command)}\n")
                log.flush()
                try:
                    self._runner(command, check=True, stdout=log, stderr=subprocess.STDOUT, text=True)
                except subprocess.CalledProcessError as exc:
                    raise UefiBootError(f"Ha fallat {' '.join(command[2:3])} amb codi {exc.returncode}; consulteu {log_path}") from exc
                except OSError as exc:
                    raise UefiBootError(f"No s'ha pogut executar chroot: {exc}") from exc
        fallback = plan.host_efi_directory / "EFI/BOOT/BOOTX64.EFI"
        if plan.removable_fallback and not fallback.is_file():
            raise UefiBootError("No s'ha generat l'entrada UEFI de fallback EFI/BOOT/BOOTX64.EFI")
        grub_cfg = plan.rootfs / "boot/grub/grub.cfg"
        if not grub_cfg.is_file():
            raise UefiBootError("No s'ha generat /boot/grub/grub.cfg")
        return UefiBootResult(plan, log_path, True, (plan.defaults_path, fallback, grub_cfg), len(commands))
