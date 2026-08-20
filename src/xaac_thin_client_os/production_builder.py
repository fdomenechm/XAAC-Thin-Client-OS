"""Independent, phased production ISO builder for XAAC Thin Client OS.

This module intentionally does not reuse the legacy image/configuration pipeline.
It creates a Debian root filesystem, configures it using paths rooted exclusively
inside the build workspace, generates SquashFS and finally creates a hybrid
BIOS/UEFI ISO with grub-mkrescue.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import tarfile
import urllib.request
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import yaml

DEVELOPMENT_DIAGNOSTICS_SCRIPT = r"""#!/bin/sh
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

if [ ! -f /etc/xaac/development-mode ]; then
    printf '%s\n' 'XAAC diagnostics is only available in development builds.' >&2
    exit 1
fi

safe_cmdline=$(cat /proc/cmdline 2>/dev/null || true)
root_source=$(findmnt -n -o SOURCE / 2>/dev/null || printf '%s' unknown)
root_fstype=$(findmnt -n -o FSTYPE / 2>/dev/null || printf '%s' unknown)
case " $safe_cmdline " in
    *' boot=live '*) system_mode=LIVE ;;
    *)
        case "$root_fstype" in
            overlay|squashfs) system_mode=LIVE ;;
            *) system_mode=INSTALLED ;;
        esac
        ;;
esac

uuid_for_source() {
    source=$1
    case "$source" in
        /dev/*) blkid -s UUID -o value "$source" 2>/dev/null || true ;;
        *) printf '%s' '' ;;
    esac
}

account_report() {
    account=$1
    printf '\n[%s identity]\n' "$account"
    if getent passwd "$account" >/dev/null 2>&1; then
        getent passwd "$account"
        id "$account"
    else
        printf 'MISSING: %s does not exist\n' "$account"
        return
    fi
    printf '[%s password state]\n' "$account"
    passwd -S "$account" 2>&1 || true
    shadow=$(getent shadow "$account" 2>/dev/null || true)
    if [ -z "$shadow" ]; then
        printf '%s\n' 'shadow: missing'
    else
        field=$(printf '%s\n' "$shadow" | cut -d: -f2)
        case $field in
            '') state=empty; prefix=none ;;
            '!') state=locked; prefix=locked ;;
            '!'*) state=locked; prefix=$(printf '%s' "${field#!}" | cut -c1-3) ;;
            '\*'*) state=locked; prefix=asterisk ;;
            '$'*) state=configured; prefix=$(printf '%s' "$field" | cut -d'$' -f2) ;;
            *) state=configured; prefix=legacy ;;
        esac
        preview=$(printf '%s' "$field" | cut -c1-4)
        [ "$state" = configured ] || preview=$(printf '%s' "$field" | cut -c1-2)
        printf 'shadow: %s (scheme=%s, length=%s, prefix=%s)\n' "$state" "$prefix" "${#field}" "$preview"
    fi
    chage -l "$account" 2>&1 || true
}

service_report() {
    unit=$1
    printf '%-34s active=%-12s enabled=%s\n' \
        "$unit" \
        "$(systemctl is-active "$unit" 2>/dev/null || true)" \
        "$(systemctl is-enabled "$unit" 2>/dev/null || true)"
}

printf '%s\n' 'XAAC Thin Client OS diagnostics (read-only)'
printf '%s\n' '==========================================='
printf 'Date: '; date -u '+%Y-%m-%dT%H:%M:%SZ'
printf 'System mode: %s\n' "$system_mode"
printf 'Kernel: '; uname -srmo
printf 'Firmware: '
if [ -d /sys/firmware/efi ]; then printf '%s\n' UEFI; else printf '%s\n' BIOS; fi
printf 'Kernel command line: %s\n' "$safe_cmdline"
printf 'Root source: %s\n' "$root_source"
printf 'Root filesystem: %s\n' "$root_fstype"
root_uuid=$(uuid_for_source "$root_source")
printf 'Root UUID: %s\n' "${root_uuid:-unavailable}"

printf '\n%s\n' '[filesystems and boot partitions]'
findmnt -rno TARGET,SOURCE,FSTYPE,OPTIONS / /boot /boot/efi 2>/dev/null || true
lsblk -o NAME,TYPE,FSTYPE,LABEL,UUID,PARTTYPE,MOUNTPOINTS 2>/dev/null || true
esp_source=$(findmnt -n -o SOURCE /boot/efi 2>/dev/null || true)
esp_uuid=$(uuid_for_source "$esp_source")
printf 'ESP source: %s\n' "${esp_source:-not-mounted}"
printf 'ESP UUID: %s\n' "${esp_uuid:-unavailable}"

printf '\n%s\n' '[network state]'
printf 'Hostname: '; hostname 2>/dev/null || true
if command -v nmcli >/dev/null 2>&1; then
    printf '%s\n' 'NetworkManager devices:'
    nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>/dev/null || true
    printf '%s\n' 'Active NetworkManager connections:'
    nmcli -t -f NAME,UUID,TYPE,DEVICE connection show --active 2>/dev/null || true
    printf '%s\n' 'IPv4 addresses:'
    nmcli -g GENERAL.DEVICE,IP4.ADDRESS device show 2>/dev/null || true
    printf '%s\n' 'IPv4 gateways:'
    nmcli -g GENERAL.DEVICE,IP4.GATEWAY device show 2>/dev/null || true
    printf '%s\n' 'DNS servers:'
    nmcli -g GENERAL.DEVICE,IP4.DNS,IP6.DNS device show 2>/dev/null || true
else
    printf '%s\n' 'nmcli: unavailable'
fi
if command -v ip >/dev/null 2>&1; then
    printf '%s\n' 'Kernel interfaces and addresses:'
    ip -brief link show 2>/dev/null || true
    ip -brief address show 2>/dev/null || true
    printf '%s\n' 'IPv4 routes:'
    ip -4 route show 2>/dev/null || true
    printf '%s\n' 'IPv6 routes:'
    ip -6 route show 2>/dev/null || true
else
    printf '%s\n' 'ip: unavailable (iproute2 is required)'
fi

printf '\n%s\n' '[GRUB and UEFI boot state]'
for cfg in /boot/grub/grub.cfg /boot/efi/EFI/BOOT/grub.cfg /boot/efi/EFI/XAAC/grub.cfg /boot/efi/EFI/debian/grub.cfg; do
    if [ -f "$cfg" ]; then
        printf 'CONFIG %s size=%s\n' "$cfg" "$(wc -c < "$cfg")"
        grep -nE '^[[:space:]]*(menuentry|linux|initrd)[[:space:]]' "$cfg" 2>/dev/null | head -n 40 || true
    else
        printf 'MISSING %s\n' "$cfg"
    fi
done
for efi in /boot/efi/EFI/BOOT/BOOTX64.EFI /boot/efi/EFI/BOOT/grubx64.efi /boot/efi/EFI/XAAC/grubx64.efi /boot/efi/EFI/debian/grubx64.efi; do
    if [ -f "$efi" ]; then
        printf 'EFI %s size=%s\n' "$efi" "$(wc -c < "$efi")"
    fi
done

account_report xaac-kiosk
account_report xaac-admin

printf '\n%s\n' '[administrative groups]'
getent group sudo 2>&1 || true

printf '\n%s\n' '[XAAC account lock directives]'
grep -RInE 'passwd[[:space:]]+--lock[[:space:]]+xaac-admin|usermod[[:space:]].*(-L|--lock)[[:space:]]+xaac-admin' /usr/local/libexec /usr/local/sbin /etc/systemd /etc/xaac 2>/dev/null || printf '%s\n' 'No runtime XAAC lock directives found.'

printf '\n%s\n' '[systemd services]'
for unit in display-manager.service getty@tty1.service getty@tty2.service ssh.service xaac-installer-welcome.service; do
    service_report "$unit"
done

printf '\n%s\n' '[PAM login stack]'
sed -n '1,160p' /etc/pam.d/login 2>/dev/null || true

printf '\n%s\n' '[recent boot and authentication messages]'
journalctl --no-pager -b -n 80 -u 'getty@tty1.service' -u 'getty@tty2.service' 2>/dev/null || true
journalctl --no-pager -b -n 80 _COMM=login 2>/dev/null || true

if [ "${1:-}" = '--pam-test' ]; then
    printf '\n%s\n' '[interactive PAM test]'
    printf '%s\n' 'Enter the xaac-admin password when prompted; it is not stored.'
    pamtester login xaac-admin authenticate
fi
"""

from xaac_thin_client_os.configuration import load_project_configuration
from xaac_thin_client_os.packages import resolve_packages
from xaac_thin_client_os.compositor import CompositorConfigurator, create_compositor_plan
from xaac_thin_client_os.graphical_stack import GraphicalStackConfigurator, create_graphical_stack_plan
from xaac_thin_client_os.session_manager import SessionManagerConfigurator, create_session_manager_plan
from xaac_thin_client_os.session_supervisor import SessionSupervisorConfigurator, create_session_supervisor_plan
from xaac_thin_client_os.local_integration import LocalIntegrationConfigurator, LocalIntegrationError
from xaac_thin_client_os.xms_enrollment import XmsEnrollmentError, XmsEnrollmentManager
from xaac_thin_client_os.thin_client_launcher import ThinClientLauncherConfigurator, create_thin_client_launcher_plan
from xaac_thin_client_os.xaac_agent_package import create_xaac_agent_plan, XaacAgentPackageError
from xaac_thin_client_os.block7_integration import (
    Block7IntegrationError,
    rootfs_verification_script,
    validate_packaged_block7_integration,
)
from xaac_thin_client_os.block7_release import (
    Block7ReleaseError,
    validate_block7_release_provenance,
)
from xaac_thin_client_os.ssh_configuration import (
    SshConfigurationError,
    SshConfigurator,
    create_ssh_configuration_plan,
)
from xaac_thin_client_os.firewall_configuration import (
    FirewallConfigurationError,
    FirewallConfigurator,
    create_firewall_configuration_plan,
)
from xaac_thin_client_os.kernel_hardening import (
    KernelHardeningError,
    KernelHardeningInstaller,
    create_kernel_hardening_plan,
)
from xaac_thin_client_os.resource_optimization import (
    ResourceConfigurator,
    ResourceOptimizationError,
    create_resource_configuration_plan,
)
from xaac_thin_client_os.systemd_hardening import (
    SystemdHardeningError,
    SystemdHardeningInstaller,
    create_systemd_hardening_plan,
)
from xaac_thin_client_os.apparmor_configuration import (
    AppArmorError,
    AppArmorInstaller,
    create_apparmor_plan,
)
from xaac_thin_client_os.update_model import (
    UpdateModelError,
    UpdateModelInstaller,
    create_update_model_plan,
    resolve_update_channel,
)
from xaac_thin_client_os.update_release_manifest import (
    UpdateReleaseManifestError,
    build_release_manifest,
    write_release_manifest,
)
from xaac_thin_client_os.transactional_update import (
    TransactionalUpdateError,
    TransactionalUpdateInstaller,
    create_transactional_update_plan,
)
from xaac_thin_client_os.package_rollback import (
    PackageRollbackError,
    PackageRollbackInstaller,
    create_package_rollback_plan,
)
from xaac_thin_client_os.maintenance_diagnostics import (
    MaintenanceDiagnosticsError,
    MaintenanceDiagnosticsInstaller,
    create_maintenance_diagnostics_plan,
)
from xaac_thin_client_os.base_os_update import (
    BaseOsUpdateError,
    BaseOsUpdateInstaller,
    create_base_os_update_plan,
)
from xaac_thin_client_os.recovery_environment import (
    RecoveryEnvironmentError,
    RecoveryEnvironmentInstaller,
    create_recovery_environment_plan,
)


class ProductionBuildError(RuntimeError):
    """Raised when a production build phase cannot complete safely."""


@dataclasses.dataclass(frozen=True, slots=True)
class BuildPaths:
    project_root: Path
    build_root: Path
    rootfs: Path
    staging: Path
    artifacts: Path
    logs: Path
    state: Path

    @classmethod
    def create(cls, project_root: Path) -> "BuildPaths":
        root = project_root.resolve()
        if root == Path("/") or not (root / "pyproject.toml").is_file():
            raise ProductionBuildError(f"Arrel de projecte invàlida: {root}")
        build_root = root / ".build" / "production"
        return cls(
            project_root=root,
            build_root=build_root,
            rootfs=build_root / "rootfs",
            staging=build_root / "iso-staging",
            artifacts=root / ".build" / "artifacts",
            logs=build_root / "logs",
            state=build_root / "state.json",
        )


@dataclasses.dataclass(frozen=True, slots=True)
class BuildSettings:
    suite: str
    mirror: str
    components: tuple[str, ...]
    architecture: str
    hostname: str
    timezone: str
    locale: str
    fallback_locales: tuple[str, ...]
    keyboard_layout: str
    keyboard_variant: str
    volume_id: str
    output_name: str
    packages: tuple[str, ...]
    kernel_parameters: tuple[str, ...]
    version: str
    profile: str
    channel: str

    @classmethod
    def load(cls, project_root: Path) -> "BuildSettings":
        configuration = load_project_configuration(project_root)
        resolved = resolve_packages(project_root, configuration)

        def yaml_mapping(relative: str) -> dict[str, object]:
            path = project_root / relative
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ProductionBuildError(f"Configuració invàlida: {relative}")
            return raw

        system = yaml_mapping("config/system.yaml")
        localization = yaml_mapping("config/localization.yaml")
        iso = yaml_mapping("config/iso-builder.yaml")
        uefi = yaml_mapping("config/uefi.yaml")
        image = iso.get("image")
        outputs = iso.get("outputs")
        if not isinstance(image, dict) or not isinstance(outputs, dict):
            raise ProductionBuildError("config/iso-builder.yaml és incomplet")
        iso_path = outputs.get("iso")
        if not isinstance(iso_path, str) or Path(iso_path).is_absolute() or ".." in Path(iso_path).parts:
            raise ProductionBuildError("Ruta d'eixida ISO invàlida")

        mandatory = {
            "live-boot",
            "sudo",
            "dbus",
            "network-manager",
            "python3",
            "python3-venv",
            "openssl",
            "pamtester",
            "plymouth",
            "greetd",
            "labwc",
            "openbox",
            "xinit",
            "xwayland",
            "python3-gi",
            "gir1.2-gtk-4.0",
            "gir1.2-gtk4layershell-1.0",
            "libgtk4-layer-shell0",
            "swaybg",
            "x11-xserver-utils",
            "socat",
            "fonts-roboto",
            "nano",
            "adwaita-icon-theme",
            "adwaita-icon-theme-legacy",
            "hicolor-icon-theme",
        }
        packages = tuple(sorted(set(resolved.packages).union(mandatory)))
        # Kernel parameters are shared by the live ISO and the installed
        # appliance.  Hardware profiles contribute platform-specific values,
        # while config/uefi.yaml owns the visual/silent boot policy.  Merge by
        # parameter name so a later policy value (for example loglevel=0)
        # replaces an older profile default instead of emitting conflicting
        # command-line options.
        kernel_parameter_order: list[str] = []
        kernel_parameter_values: dict[str, str] = {}

        def merge_kernel_parameters(values: object) -> None:
            if not isinstance(values, list):
                return
            for raw_value in values:
                if not isinstance(raw_value, str) or not raw_value:
                    continue
                key = raw_value.split("=", 1)[0]
                if key not in kernel_parameter_values:
                    kernel_parameter_order.append(key)
                kernel_parameter_values[key] = raw_value

        for profile_name in resolved.profile_chain:
            profile_raw = yaml_mapping(f"profiles/{profile_name}/profile.yaml")
            merge_kernel_parameters(profile_raw.get("kernel_parameters", []))
        merge_kernel_parameters(uefi.get("kernel_parameters", []))

        fallback = localization.get("fallback_locales", [])
        return cls(
            suite=configuration.build.debian.suite,
            mirror=configuration.build.debian.mirror,
            components=tuple(configuration.build.debian.components),
            architecture=configuration.build.architecture.value,
            hostname=str(system.get("hostname", "xaac-thin-client")),
            timezone=str(localization.get("timezone", "Europe/Madrid")),
            locale=str(localization.get("locale", "ca_ES.UTF-8")),
            fallback_locales=tuple(str(v) for v in fallback if isinstance(v, str)),
            keyboard_layout=str(localization.get("keyboard", {}).get("layout", "es")) if isinstance(localization.get("keyboard"), dict) else "es",
            keyboard_variant=str(localization.get("keyboard", {}).get("variant", "cat")) if isinstance(localization.get("keyboard"), dict) else "cat",
            volume_id=str(image.get("volume_id", "XAAC_TC_OS")),
            output_name=Path(iso_path).name,
            packages=packages,
            kernel_parameters=tuple(kernel_parameter_values[key] for key in kernel_parameter_order),
            version=configuration.build.version,
            profile=configuration.build.profile,
            channel=configuration.build.channel.value,
        )


class CommandRunner:
    """Run commands with per-phase logs and useful error reporting."""

    def __init__(self, logs: Path, *, dry_run: bool = False) -> None:
        self.logs = logs
        self.dry_run = dry_run
        self.logs.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        command: Sequence[str],
        *,
        phase: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        # The workspace may have been removed by --clean after the runner was
        # created. Recreate the log directory immediately before every command
        # so each phase can always record its diagnostics.
        self.logs.mkdir(parents=True, exist_ok=True)
        log_path = self.logs / f"{phase}.log"
        rendered = " ".join(command)
        if self.dry_run:
            log_path.write_text(f"$ {rendered}\n", encoding="utf-8")
            return
        started = time.monotonic()
        print(f"[XAAC]   -> {phase} (log: {log_path})", flush=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"$ {rendered}\n")
            log.flush()
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            next_report = started + 30.0
            while True:
                returncode = process.poll()
                if returncode is not None:
                    break
                now = time.monotonic()
                if now >= next_report:
                    elapsed = int(now - started)
                    print(
                        f"[XAAC]      {phase}: continua en execució ({elapsed}s)...",
                        flush=True,
                    )
                    next_report = now + 30.0
                time.sleep(1.0)
        elapsed = time.monotonic() - started
        if returncode != 0:
            print(
                f"[XAAC]   !! {phase}: ha fallat després de {elapsed:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            raise ProductionBuildError(
                f"Ha fallat la fase {phase!r} (codi {returncode}). "
                f"Consulta {log_path}"
            )
        print(f"[XAAC]   <- {phase}: completada ({elapsed:.1f}s)", flush=True)


class ProductionIsoBuilder:
    """A deterministic set of independent build phases."""

    PHASES = ("rootfs", "configure", "boot", "squashfs", "iso", "verify")

    def __init__(self, project_root: Path, *, dry_run: bool = False) -> None:
        self.paths = BuildPaths.create(project_root)
        self.settings = BuildSettings.load(self.paths.project_root)
        self.runner = CommandRunner(self.paths.logs, dry_run=dry_run)
        self.dry_run = dry_run

    def _require_root(self) -> None:
        if not self.dry_run and os.geteuid() != 0:
            raise ProductionBuildError("La construcció del rootfs requereix privilegis de root")

    @staticmethod
    def _atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
        if path.is_symlink():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)


    def _verify_thinclient_rootfs(self, *, context: str) -> None:
        """Fail closed unless the real XAAC Thin Client package is present."""
        if self.dry_run:
            return
        binary = self._inside("/usr/bin/xaac-thinclient")
        status = self._inside("/var/lib/dpkg/status")
        config_dir = self._inside("/etc/xaac-thinclient")
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ProductionBuildError(
                f"{context}: falta /usr/bin/xaac-thinclient executable al rootfs"
            )
        if not config_dir.is_dir():
            raise ProductionBuildError(
                f"{context}: falta /etc/xaac-thinclient al rootfs"
            )
        text = status.read_text(encoding="utf-8", errors="replace") if status.is_file() else ""
        if "Package: xaac-thinclient\n" not in text or "Version: 1.0.0\n" not in text:
            raise ProductionBuildError(
                f"{context}: xaac-thinclient 1.0.0 no consta en la base de dades dpkg"
            )

    def _inside(self, absolute: str) -> Path:
        """Return a host path lexically confined to the build rootfs.

        Do not resolve the destination itself: files such as ``/etc/localtime``
        are legitimate absolute symlinks inside a Debian rootfs. Resolving that
        leaf from the host would incorrectly turn it into
        ``/usr/share/zoneinfo/...`` on the host and trigger a false escape.

        Parent directories are still checked when they already exist, so an
        unexpected symlinked parent cannot redirect writes outside the rootfs.
        """
        candidate = Path(absolute)
        if not candidate.is_absolute():
            raise ProductionBuildError(f"Ruta de rootfs no absoluta: {absolute}")
        if ".." in candidate.parts:
            raise ProductionBuildError(f"Ruta fora del rootfs: {absolute}")

        rootfs = self.paths.rootfs.absolute()
        destination = rootfs.joinpath(*candidate.parts[1:])
        try:
            if os.path.commonpath((str(rootfs), str(destination))) != str(rootfs):
                raise ProductionBuildError(f"Ruta fora del rootfs: {absolute}")
        except ValueError as exc:
            raise ProductionBuildError(f"Ruta fora del rootfs: {absolute}") from exc

        current = rootfs
        for part in candidate.parts[1:-1]:
            current = current / part
            if current.is_symlink():
                resolved_parent = current.resolve(strict=False)
                if not resolved_parent.is_relative_to(rootfs.resolve(strict=False)):
                    raise ProductionBuildError(
                        f"Un directori pare ix fora del rootfs: {absolute}"
                    )
        return destination

    def _save_state(self, phase: str) -> None:
        if self.dry_run:
            return
        self.paths.state.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "phase": phase,
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            "suite": self.settings.suite,
            "architecture": self.settings.architecture,
            "version": self.settings.version,
            "profile": self.settings.profile,
        }
        self._atomic_write(self.paths.state, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def _chroot_mount_targets(self) -> tuple[Path, ...]:
        """Return the top-level mount trees owned by this production rootfs."""
        return (
            self._inside("/dev"),
            self._inside("/proc"),
            self._inside("/sys"),
            self._inside("/run"),
        )

    @staticmethod
    def _decode_mountinfo_path(value: str) -> str:
        """Decode the octal escapes used by ``/proc/self/mountinfo``."""
        replacements = {
            r"\040": " ",
            r"\011": "\t",
            r"\012": "\n",
            r"\134": "\\",
        }
        for escaped, plain in replacements.items():
            value = value.replace(escaped, plain)
        return value

    def _mounted_paths_below_rootfs(self) -> tuple[Path, ...]:
        """List chroot mount points, deepest first, without following host trees.

        Reading ``mountinfo`` directly is more reliable than ``umount -R``: it
        lets us detach every nested mount (for example ``/sys/fs/cgroup`` and
        ``/dev/pts``) in the correct order while strictly confining all targets
        to the production rootfs.
        """
        if not self.paths.rootfs.exists():
            return ()

        rootfs = self.paths.rootfs.resolve(strict=False)
        allowed_roots = tuple(path.resolve(strict=False) for path in self._chroot_mount_targets())
        mounted: set[Path] = set()
        try:
            lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ProductionBuildError(f"No s'ha pogut llegir /proc/self/mountinfo: {exc}") from exc

        for line in lines:
            fields = line.split()
            if len(fields) < 5:
                continue
            mountpoint = Path(self._decode_mountinfo_path(fields[4])).resolve(strict=False)
            if mountpoint == rootfs or not mountpoint.is_relative_to(rootfs):
                continue
            if not any(mountpoint == top or mountpoint.is_relative_to(top) for top in allowed_roots):
                continue
            mounted.add(mountpoint)

        return tuple(sorted(mounted, key=lambda path: (len(path.parts), str(path)), reverse=True))

    def _mount_users(self, target: Path) -> str:
        """Return best-effort diagnostics for processes using a mountpoint."""
        if shutil.which("fuser") is None:
            return "fuser no està disponible"
        result = subprocess.run(
            ["fuser", "-vm", str(target)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output = result.stdout.strip()
        return output or "cap procés identificat per fuser"

    def _chroot_processes(self) -> tuple[int, ...]:
        """Return processes whose root/cwd/executable is inside this rootfs.

        This deliberately ignores ordinary host processes merely accessing a
        bind-mounted device. Only processes demonstrably attached to the chroot
        namespace are eligible for termination.
        """
        if not self.paths.rootfs.exists():
            return ()
        rootfs = self.paths.rootfs.resolve(strict=False)
        own_pid = os.getpid()
        found: set[int] = set()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid in (1, own_pid, os.getppid()):
                continue
            for link_name in ("root", "cwd", "exe"):
                try:
                    target = (entry / link_name).resolve(strict=True)
                except (FileNotFoundError, PermissionError, OSError):
                    continue
                if target == rootfs or target.is_relative_to(rootfs):
                    found.add(pid)
                    break
        return tuple(sorted(found))

    def _stop_chroot_processes(self) -> None:
        """Terminate leftover chroot processes before attempting unmounts."""
        if getattr(self, "dry_run", False):
            return
        pids = self._chroot_processes()
        if not pids:
            return
        for pid in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, 15)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            remaining = self._chroot_processes()
            if not remaining:
                return
            time.sleep(0.1)
        for pid in self._chroot_processes():
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, 9)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and self._chroot_processes():
            time.sleep(0.05)
        remaining = self._chroot_processes()
        if remaining:
            raise ProductionBuildError(
                "No s'han pogut aturar els processos residuals del chroot: "
                + ", ".join(str(pid) for pid in remaining)
            )

    def cleanup_chroot_mounts(self) -> None:
        """Safely detach all nested chroot mounts without touching the host.

        Bind-mounted trees are detached deepest-first.  Transient ``EBUSY``
        failures are retried after ``sync`` because package hooks and chroot
        helpers can keep short-lived file descriptors open after their parent
        command exits.  No lazy, forced, or recursive unmount is used.
        """
        if getattr(self, "dry_run", False) or not self.paths.rootfs.exists():
            return

        rootfs = self.paths.rootfs.resolve(strict=False)
        max_attempts = 10
        retry_delay = 0.2
        last_errors: dict[Path, str] = {}

        self._stop_chroot_processes()
        subprocess.run(["sync"], check=False)
        for attempt in range(max_attempts):
            mounted = self._mounted_paths_below_rootfs()
            if not mounted:
                return

            progress = False
            last_errors.clear()
            for target in mounted:
                resolved = target.resolve(strict=False)
                if not resolved.is_relative_to(rootfs):
                    raise ProductionBuildError(f"Punt de muntatge fora del rootfs: {target}")
                result = subprocess.run(
                    ["umount", str(target)],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                if result.returncode == 0:
                    progress = True
                else:
                    last_errors[target] = (getattr(result, "stdout", "") or "").strip() or f"codi {result.returncode}"

            if not self._mounted_paths_below_rootfs():
                return
            if attempt < max_attempts - 1:
                subprocess.run(["sync"], check=False)
                time.sleep(retry_delay)
            if not progress and attempt == max_attempts - 1:
                break

        remaining = self._mounted_paths_below_rootfs()
        if remaining:
            diagnostics: list[str] = []
            for path in remaining:
                reason = last_errors.get(path, "continua muntat")
                users = self._mount_users(path)
                diagnostics.append(f"{path}: {reason}; processos: {users}")
            raise ProductionBuildError(
                "No s'han pogut desmuntar de manera segura els muntatges del chroot: "
                + " | ".join(diagnostics)
            )

    def _assert_chroot_unmounted(self, operation: str) -> None:
        """Refuse destructive operations while host-backed chroot mounts exist."""
        mounted = self._mounted_paths_below_rootfs()
        if mounted:
            raise ProductionBuildError(
                f"Operació insegura ({operation}): encara hi ha muntatges actius dins del rootfs: "
                + ", ".join(str(path) for path in mounted)
            )

    def clean(self) -> None:
        target = self.paths.build_root.resolve(strict=False)
        allowed_parent = (self.paths.project_root / ".build").resolve(strict=False)
        if target.parent != allowed_parent or target.name != "production":
            raise ProductionBuildError(f"Directori de neteja insegur: {target}")
        self.cleanup_chroot_mounts()
        self._assert_chroot_unmounted("neteja del workspace")
        if target.exists():
            shutil.rmtree(target)

    def phase_rootfs(self) -> None:
        """Bootstrap only the minimal Debian base system.

        Runtime packages are deliberately installed later, from inside the
        chroot.  This keeps debootstrap focused on the base system and allows
        packages from contrib/non-free-firmware to be resolved by apt using
        the configured repository components.
        """
        self._require_root()
        self.cleanup_chroot_mounts()
        self._assert_chroot_unmounted("recreació del rootfs")
        if self.paths.rootfs.exists():
            shutil.rmtree(self.paths.rootfs)
        self.paths.rootfs.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "debootstrap",
            "--arch", self.settings.architecture,
            "--variant=minbase",
            f"--components={','.join(self.settings.components)}",
        ]
        keyring = Path("/usr/share/keyrings/debian-archive-keyring.gpg")
        if keyring.is_file():
            command.append(f"--keyring={keyring}")
        command.extend([
            self.settings.suite,
            str(self.paths.rootfs),
            self.settings.mirror,
        ])
        self.runner.run(command, phase="rootfs-debootstrap")
        self._save_state("rootfs")

    @contextlib.contextmanager
    def _chroot_mounts(self) -> Iterator[None]:
        mounts = (
            ("/dev", "rbind"),
            ("/proc", "proc"),
            ("/sys", "rbind"),
            ("/run", "rbind"),
        )
        self.cleanup_chroot_mounts()
        try:
            for source, mode in mounts:
                target = self._inside(source)
                target.mkdir(parents=True, exist_ok=True)
                if mode == "proc":
                    command = ["mount", "-t", "proc", "proc", str(target)]
                else:
                    command = ["mount", "--rbind", source, str(target)]
                self.runner.run(command, phase=f"mount-{source.strip('/').replace('/', '-') or 'root'}")
                if mode == "rbind":
                    # Prevent unmount operations below the chroot from
                    # propagating back to the host's shared mount tree.
                    self.runner.run(
                        ["mount", "--make-rslave", str(target)],
                        phase=f"mount-rslave-{source.strip('/').replace('/', '-')}",
                    )
            yield
        finally:
            self.cleanup_chroot_mounts()

    def _chroot(self, command: Sequence[str], *, phase: str) -> None:
        env = os.environ.copy()
        env.update({"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C.UTF-8"})
        self.runner.run(["chroot", str(self.paths.rootfs), *command], phase=phase, env=env)

    def _validate_xaac_agent_artifact(self) -> str:
        try:
            plan = create_xaac_agent_plan(
                self.paths.rootfs,
                self.paths.project_root,
                self.paths.project_root / "config/xaac-agent-package.yaml",
            )
            validate_packaged_block7_integration(self.paths.project_root)
            validate_block7_release_provenance(self.paths.project_root, require_canonical=True)
        except (XaacAgentPackageError, Block7IntegrationError, Block7ReleaseError) as exc:
            raise ProductionBuildError(f"Integració XAAC Agent invàlida: {exc}") from exc
        return plan.metadata.version

    def _verify_block7_rootfs(self, *, context: str) -> None:
        profile = load_project_configuration(self.paths.project_root)
        del profile  # force normal project configuration validation as part of the gate
        package = yaml.safe_load(
            (self.paths.project_root / "config/xaac-agent-package.yaml").read_text(encoding="utf-8")
        )
        version = str(package["package"]["version"])
        self._chroot(
            ["/bin/sh", "-ec", rootfs_verification_script(version)],
            phase=f"{context}-verify-block7-integration",
        )

    def _copy_valid_debs(self) -> list[str]:
        source_dir = self.paths.project_root / "packages"
        target_dir = self._inside("/tmp/xaac-packages")
        target_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for package in sorted(source_dir.glob("*.deb")):
            try:
                if package.read_bytes()[:8] != b"!<arch>\n":
                    continue
            except OSError:
                continue
            destination = target_dir / package.name
            shutil.copy2(package, destination)
            copied.append(f"/tmp/xaac-packages/{package.name}")
        return copied

    def _write_apt_sources(self) -> None:
        components = " ".join(self.settings.components)
        suite = self.settings.suite
        mirror = self.settings.mirror.rstrip("/")
        keyring = "/usr/share/keyrings/debian-archive-keyring.gpg"
        sources = (
            f"deb [signed-by={keyring}] {mirror} {suite} {components}\n"
            f"deb [signed-by={keyring}] {mirror} {suite}-updates {components}\n"
            f"deb [signed-by={keyring}] https://security.debian.org/debian-security {suite}-security {components}\n"
        )
        self._atomic_write(self._inside("/etc/apt/sources.list"), sources)

    def _prepare_chroot_network(self) -> None:
        host_resolv = Path("/etc/resolv.conf")
        content = host_resolv.read_text(encoding="utf-8") if host_resolv.exists() else "nameserver 1.1.1.1\n"
        self._atomic_write(self._inside("/etc/resolv.conf"), content)

    def _install_runtime_packages(self) -> None:
        self._chroot(["apt-get", "update"], phase="configure-apt-update")
        # DEBIAN_FRONTEND=noninteractive does not answer dpkg conffile prompts.
        # Keep files intentionally prepared by the image builder and never let
        # an unattended ISO build wait for an invisible Y/I/N/O question.
        self._chroot([
            "apt-get", "install", "--yes", "--no-install-recommends",
            "-o", "Dpkg::Options::=--force-confdef",
            "-o", "Dpkg::Options::=--force-confold",
            *self.settings.packages,
        ], phase="configure-apt-install")

    def _apply_kiosk_stack(self) -> None:
        """Apply XAAC-owned kiosk configuration after Debian packages exist.

        In particular, greetd ships /etc/greetd/config.toml as a conffile.
        Writing our version before apt installs greetd makes dpkg ask an
        interactive conffile question and stalls the unattended build.
        """
        GraphicalStackConfigurator().execute(
            create_graphical_stack_plan(self.paths.rootfs, self.paths.project_root / "config/graphical-stack.yaml")
        )
        CompositorConfigurator().execute(
            create_compositor_plan(self.paths.rootfs, self.paths.project_root / "config/compositor.yaml")
        )
        SessionManagerConfigurator().execute(
            create_session_manager_plan(self.paths.rootfs, self.paths.project_root / "config/session-manager.yaml")
        )
        ThinClientLauncherConfigurator().execute(
            create_thin_client_launcher_plan(self.paths.rootfs, self.paths.project_root / "config/thin-client-launcher.yaml")
        )
        SessionSupervisorConfigurator().execute(
            create_session_supervisor_plan(self.paths.rootfs, self.paths.project_root / "config/session-supervisor.yaml")
        )
        self._atomic_write(
            self._inside("/etc/systemd/system/xaac-boot-handoff.service"),
            "[Unit]\n"
            "Description=Prepare XAAC canvas before Plymouth releases the display\n"
            "ConditionKernelCommandLine=!xaac.mode=installer\n"
            "After=plymouth-start.service systemd-vconsole-setup.service\n"
            "Before=plymouth-quit.service greetd.service\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/usr/local/libexec/xaac-prepare-kiosk-vt\n"
            "ExecStartPost=-/usr/bin/plymouth quit --retain-splash\n"
            "RemainAfterExit=yes\n\n"
            "[Install]\n"
            "WantedBy=graphical.target\n",
        )
        self._atomic_write(
            self._inside("/etc/systemd/system/greetd.service.d/10-xaac-mode.conf"),
            "[Unit]\n"
            "ConditionKernelCommandLine=!xaac.mode=installer\n"
            "Wants=xaac-boot-handoff.service\n"
            "After=xaac-boot-handoff.service\n",
        )
        self._chroot(
            ["systemctl", "enable", "xaac-boot-handoff.service"],
            phase="configure-boot-handoff",
        )

    def _configure_production_network_hardening(self) -> None:
        """Apply the canonical SSH and nftables policies to the production rootfs.

        The production ISO builder is intentionally independent from the legacy
        image pipeline, so these policies must be applied explicitly here.  SSH
        stays disabled at boot when config/ssh.yaml says so; the temporary access
        helper can still start it on demand.  nftables is enabled with the
        default-deny input/forward policy from config/firewall.yaml.
        """
        try:
            ssh_plan = create_ssh_configuration_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/ssh.yaml",
            )
            SshConfigurator().execute(
                ssh_plan,
                self.paths.logs / "configure-ssh-hardening.log",
                dry_run=self.dry_run,
            )
            firewall_plan = create_firewall_configuration_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/firewall.yaml",
                self.paths.project_root / "config/ssh.yaml",
            )
            FirewallConfigurator().execute(
                firewall_plan,
                self.paths.logs / "configure-firewall-hardening.log",
                dry_run=self.dry_run,
            )
        except (SshConfigurationError, FirewallConfigurationError) as exc:
            raise ProductionBuildError(
                f"No s'ha pogut aplicar el hardening de xarxa de producció: {exc}"
            ) from exc

        if self.dry_run:
            return

        self._chroot(["sshd", "-t"], phase="configure-verify-sshd")
        self._chroot(["nft", "-c", "-f", "/etc/nftables.conf"], phase="configure-verify-nftables")
        self._chroot(
            [
                "/bin/sh", "-ec",
                "test -f /etc/ssh/sshd_config.d/20-xaac-hardening.conf; "
                "grep -Fx 'PasswordAuthentication no' /etc/ssh/sshd_config.d/20-xaac-hardening.conf >/dev/null; "
                "grep -Fx 'PermitRootLogin no' /etc/ssh/sshd_config.d/20-xaac-hardening.conf >/dev/null; "
                "test -x /usr/local/sbin/xaac-ssh-access; "
                "! systemctl is-enabled --quiet ssh.service; "
                "systemctl is-enabled --quiet nftables.service; "
                "grep -F 'policy drop' /etc/nftables.conf >/dev/null",
            ],
            phase="configure-verify-network-hardening",
        )

    def _configure_production_kernel_resources(self) -> None:
        """Apply kernel, RAM and eMMC policies to the production rootfs.

        The policy is installed as static configuration only; the builder must
        never run sysctl against the chroot because that would modify the host
        kernel.  Runtime activation is therefore validated structurally and is
        left to the target boot.
        """
        try:
            kernel_plan = create_kernel_hardening_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/kernel-hardening.yaml",
            )
            KernelHardeningInstaller().install(kernel_plan, dry_run=self.dry_run)
            resource_plan = create_resource_configuration_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/resources.yaml",
            )
            missing_packages = sorted(set(resource_plan.packages) - set(self.settings.packages))
            if missing_packages:
                raise ProductionBuildError(
                    "La política de recursos requereix paquets absents del build: "
                    + ", ".join(missing_packages)
                )
            ResourceConfigurator().execute(resource_plan, dry_run=self.dry_run)
        except (KernelHardeningError, ResourceOptimizationError) as exc:
            raise ProductionBuildError(
                f"No s'ha pogut aplicar el hardening de kernel/recursos: {exc}"
            ) from exc

        if self.dry_run:
            return

        self._chroot(
            [
                "/bin/sh", "-ec",
                "test -f /etc/sysctl.d/90-xaac-hardening.conf; "
                "grep -Fx 'kernel.randomize_va_space = 2' /etc/sysctl.d/90-xaac-hardening.conf >/dev/null; "
                "grep -Fx 'kernel.yama.ptrace_scope = 2' /etc/sysctl.d/90-xaac-hardening.conf >/dev/null; "
                "grep -Fx 'kernel.sysrq = 0' /etc/sysctl.d/90-xaac-hardening.conf >/dev/null; "
                "grep -Fx 'install sctp /bin/false' /etc/modprobe.d/xaac-hardening.conf >/dev/null; "
                "! grep -Eq '^(install|blacklist)[[:space:]]+squashfs([[:space:]]|$)' /etc/modprobe.d/xaac-hardening.conf; "
                "test -f /etc/systemd/zram-generator.conf; "
                "grep -F 'zram-size = ram * 50 / 100' /etc/systemd/zram-generator.conf >/dev/null; "
                "grep -Fx 'vm.swappiness = 100' /etc/sysctl.d/70-xaac-memory.conf >/dev/null; "
                "grep -Fx 'Storage=Volatile' /etc/systemd/journald.conf.d/xaac-limits.conf >/dev/null; "
                "grep -Fx 'RuntimeMaxUse=32M' /etc/systemd/journald.conf.d/xaac-limits.conf >/dev/null; "
                "test \"$(readlink /etc/systemd/system/local-fs.target.wants/tmp.mount)\" = '/lib/systemd/system/tmp.mount'; "
                "test \"$(readlink /etc/systemd/system/timers.target.wants/fstrim.timer)\" = '/lib/systemd/system/fstrim.timer'; "
                "test -e /lib/systemd/system/tmp.mount; test -e /lib/systemd/system/fstrim.timer; "
                "test \"$(readlink /etc/systemd/system/apt-daily.service)\" = '/dev/null'; "
                "test \"$(readlink /etc/systemd/system/apt-daily.timer)\" = '/dev/null'; "
                "test \"$(readlink /etc/systemd/system/apt-daily-upgrade.service)\" = '/dev/null'; "
                "test \"$(readlink /etc/systemd/system/apt-daily-upgrade.timer)\" = '/dev/null'; "
                "dpkg-query -W -f='${Status}' systemd-zram-generator | grep -Fx 'install ok installed' >/dev/null",
            ],
            phase="configure-verify-kernel-resources",
        )

    def _configure_production_service_hardening(self) -> None:
        """Harden the effective services and install AppArmor audit profiles.

        Package-owned Agent units remain authoritative: the OS verifies their
        least-privilege contract instead of layering a generic drop-in that
        could accidentally broaden capabilities.  The VPN manager receives the
        OS-owned hardening drop-in.  Custom AppArmor profiles are installed in
        complain mode for the complex Python/GUI entry points so the 9.4
        physical gate can observe real accesses before any enforce promotion.

        AppArmor profiles are syntax-checked with ``apparmor_parser -Q``.  They
        are never loaded into the builder host kernel from inside the chroot.
        """
        try:
            systemd_plan = create_systemd_hardening_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/systemd-hardening.yaml",
            )
            SystemdHardeningInstaller().install(systemd_plan, dry_run=self.dry_run)
            apparmor_plan = create_apparmor_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/apparmor.yaml",
            )
            AppArmorInstaller().install(apparmor_plan, dry_run=self.dry_run)
        except (SystemdHardeningError, AppArmorError) as exc:
            raise ProductionBuildError(
                f"No s'ha pogut aplicar el hardening de serveis/AppArmor: {exc}"
            ) from exc

        if self.dry_run:
            return

        self._chroot(
            ["systemctl", "enable", "apparmor.service"],
            phase="configure-enable-apparmor",
        )
        self._chroot(
            [
                "/bin/sh", "-ec",
                # Agent: the package owns this sandbox.  Verify it and, above
                # all, ensure the OS has not reintroduced CAP_NET_ADMIN.
                "test -f /usr/lib/systemd/system/xaac-agent.service; "
                "grep -Fx 'NoNewPrivileges=true' /usr/lib/systemd/system/xaac-agent.service >/dev/null; "
                "grep -Fx 'ProtectSystem=strict' /usr/lib/systemd/system/xaac-agent.service >/dev/null; "
                "grep -Fx 'ProtectKernelTunables=true' /usr/lib/systemd/system/xaac-agent.service >/dev/null; "
                "grep -Fx 'ProtectKernelModules=true' /usr/lib/systemd/system/xaac-agent.service >/dev/null; "
                "grep -Fx 'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK' /usr/lib/systemd/system/xaac-agent.service >/dev/null; "
                "grep -Fx 'CapabilityBoundingSet=' /usr/lib/systemd/system/xaac-agent.service >/dev/null; "
                "! grep -F 'CAP_NET_ADMIN' /usr/lib/systemd/system/xaac-agent.service >/dev/null; "
                # Privileged helper: CAP_SYS_BOOT is the sole deliberate
                # capability and the service remains local-socket only.
                "test -f /usr/lib/systemd/system/xaac-privileged-helper.service; "
                "grep -Fx 'ProtectSystem=strict' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null; "
                "grep -Fx 'RestrictAddressFamilies=AF_UNIX' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null; "
                "grep -Fx 'CapabilityBoundingSet=CAP_SYS_BOOT' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null; "
                "! grep -F 'CAP_SYS_ADMIN' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null; "
                # The VPN manager is the only current system service receiving
                # the generic OS hardening policy in phase 9.3.
                "test -f /lib/systemd/system/xaac-vpn-manager.service; "
                "test -f /etc/systemd/system/xaac-vpn-manager.service.d/90-xaac-hardening.conf; "
                "grep -Fx 'NoNewPrivileges=yes' /etc/systemd/system/xaac-vpn-manager.service.d/90-xaac-hardening.conf >/dev/null; "
                "grep -Fx 'ProtectSystem=strict' /etc/systemd/system/xaac-vpn-manager.service.d/90-xaac-hardening.conf >/dev/null; "
                "grep -Fx 'MemoryDenyWriteExecute=yes' /etc/systemd/system/xaac-vpn-manager.service.d/90-xaac-hardening.conf >/dev/null; "
                "grep -Fx 'RestrictNamespaces=yes' /etc/systemd/system/xaac-vpn-manager.service.d/90-xaac-hardening.conf >/dev/null; "
                "grep -Fx 'CapabilityBoundingSet=' /etc/systemd/system/xaac-vpn-manager.service.d/90-xaac-hardening.conf >/dev/null; "
                "grep -Fx 'SystemCallFilter=@system-service ~@mount ~@reboot ~@swap' /etc/systemd/system/xaac-vpn-manager.service.d/90-xaac-hardening.conf >/dev/null; "
                "systemctl is-enabled --quiet apparmor.service; "
                # Profiles must point at the executables that actually exist in
                # the current .deb set.  All remain complain-only pre-9.4.
                "test -x /usr/bin/xaac-agent; test -x /usr/bin/xaac-thinclient; test -x /usr/bin/xaac-thin-client-vpn; "
                "test -f /etc/apparmor.d/usr.bin.xaac-agent; "
                "test -f /etc/apparmor.d/usr.bin.xaac-thinclient; "
                "test -f /etc/apparmor.d/usr.bin.xaac-thin-client-vpn; "
                "test \"$(readlink /etc/apparmor.d/force-complain/usr.bin.xaac-agent)\" = '../usr.bin.xaac-agent'; "
                "test \"$(readlink /etc/apparmor.d/force-complain/usr.bin.xaac-thinclient)\" = '../usr.bin.xaac-thinclient'; "
                "test \"$(readlink /etc/apparmor.d/force-complain/usr.bin.xaac-thin-client-vpn)\" = '../usr.bin.xaac-thin-client-vpn'; "
                "! test -e /etc/apparmor.d/usr.sbin.xaac-agent; "
                "! test -e /etc/apparmor.d/usr.bin.xaac-thin-client",
            ],
            phase="configure-verify-service-hardening",
        )
        self._chroot(
            [
                "systemd-analyze", "verify",
                "xaac-agent.service",
                "xaac-privileged-helper.service",
                "xaac-vpn-manager.service",
            ],
            phase="configure-verify-systemd-units",
        )
        self._chroot(
            [
                "apparmor_parser", "-Q", "-K",
                "/etc/apparmor.d/usr.bin.xaac-agent",
                "/etc/apparmor.d/usr.bin.xaac-thinclient",
                "/etc/apparmor.d/usr.bin.xaac-thin-client-vpn",
            ],
            phase="configure-verify-apparmor-syntax",
        )

    def _install_block9_target_validation(self) -> None:
        """Install the read-only Block 9.4 target validation gate.

        The validator is deliberately a small POSIX shell script.  It collects
        evidence from the installed Wyse without changing policy, enabling
        services or loading AppArmor profiles.  Keeping it in /usr/local/sbin
        makes the final physical validation reproducible while limiting normal
        kiosk exposure.
        """
        source = self.paths.project_root / "assets/runtime/xaac-block9-validate"
        if not source.is_file():
            raise ProductionBuildError("Falta assets/runtime/xaac-block9-validate")
        target = self._inside("/usr/local/sbin/xaac-block9-validate")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        target.chmod(0o750)
        if self.dry_run:
            return
        self._chroot(
            [
                "/bin/sh", "-ec",
                "test -x /usr/local/sbin/xaac-block9-validate; "
                "sh -n /usr/local/sbin/xaac-block9-validate; "
                "test \"$(stat -c '%U:%G:%a' /usr/local/sbin/xaac-block9-validate)\" = 'root:root:750'",
            ],
            phase="configure-verify-block9-target-validator",
        )

    def _install_block10_target_validation(self) -> None:
        """Install the read-only Block 10.6 target qualification gate.

        The gate composes the already validated Block 9 hardware/hardening gate
        with update, maintenance and recovery checks.  It never installs an
        update or performs rollback itself; destructive qualification remains an
        explicit administrator action on the physical Wyse.
        """
        source = self.paths.project_root / "assets/runtime/xaac-block10-validate"
        if not source.is_file():
            raise ProductionBuildError("Falta assets/runtime/xaac-block10-validate")
        target = self._inside("/usr/local/sbin/xaac-block10-validate")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        target.chmod(0o750)
        if self.dry_run:
            return
        self._chroot(
            [
                "/bin/sh", "-ec",
                "test -x /usr/local/sbin/xaac-block10-validate; "
                "sh -n /usr/local/sbin/xaac-block10-validate; "
                "grep -F '/usr/local/sbin/xaac-block9-validate' "
                "/usr/local/sbin/xaac-block10-validate >/dev/null; "
                "grep -F 'xaac-update-admin --json status' "
                "/usr/local/sbin/xaac-block10-validate >/dev/null; "
                "grep -F 'xaac-update-admin --json os-status' "
                "/usr/local/sbin/xaac-block10-validate >/dev/null; "
                "grep -F 'base OS update policy v1' "
                "/usr/local/sbin/xaac-block10-validate >/dev/null; "
                "grep -F 'xaac-maintenance health' "
                "/usr/local/sbin/xaac-block10-validate >/dev/null; "
                "grep -F 'xaac-recovery status' "
                "/usr/local/sbin/xaac-block10-validate >/dev/null; "
                "test \"$(stat -c '%U:%G:%a' /usr/local/sbin/xaac-block10-validate)\" "
                "= 'root:root:750'",
            ],
            phase="configure-verify-block10-target-validator",
        )

    def _configure_update_architecture(self) -> None:
        """Install phases 10.1/10.2 update contract, transaction runtime and rollback cache."""
        try:
            model_plan = create_update_model_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/update-model.yaml",
            )
            UpdateModelInstaller().install(model_plan)
            manifest = build_release_manifest(
                self.paths.project_root,
                self.paths.project_root / "config/update-model.yaml",
                target_os_version=self.settings.version,
                channel=resolve_update_channel(model_plan.profile, self.settings.channel),
            )
            write_release_manifest(model_plan.output("current_release"), manifest)

            transaction_plan = create_transactional_update_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/transactional-update.yaml",
            )
            TransactionalUpdateInstaller().install(transaction_plan)
            rollback_plan = create_package_rollback_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/package-rollback.yaml",
            )
            PackageRollbackInstaller().install(rollback_plan)
        except (
            UpdateModelError,
            UpdateReleaseManifestError,
            TransactionalUpdateError,
            PackageRollbackError,
        ) as exc:
            raise ProductionBuildError(f"Arquitectura d'actualització 10.2 invàlida: {exc}") from exc

        admin_source = self.paths.project_root / "assets/runtime/xaac-update-admin"
        runtime_source = self.paths.project_root / "assets/runtime/xaac_update_runtime.py"
        if not admin_source.is_file():
            raise ProductionBuildError("Falta assets/runtime/xaac-update-admin")
        if not runtime_source.is_file():
            raise ProductionBuildError("Falta assets/runtime/xaac_update_runtime.py")
        admin_target = model_plan.output("admin")
        runtime_target = transaction_plan.output("runtime")
        admin_target.parent.mkdir(parents=True, exist_ok=True)
        runtime_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(admin_source, admin_target)
        shutil.copy2(runtime_source, runtime_target)
        admin_target.chmod(0o750)
        runtime_target.chmod(0o640)

        # Seed the exact baseline .deb files into a root-only cache. This makes
        # the very first rollback independent of network/repository availability.
        package_cache = self._inside(transaction_plan.profile["recovery_point"]["package_cache"])
        for component in manifest["components"]:
            source = self.paths.project_root / "packages" / component["filename"]
            if not source.is_file():
                raise ProductionBuildError(f"Falta el paquet base de rollback: {source}")
            version_dir = str(component["version"]).replace(":", "_")
            target = package_cache / component["package"] / f"{version_dir}.deb"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.parent.chmod(0o700)
            shutil.copy2(source, target)
            target.chmod(0o600)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != component["sha256"]:
                raise ProductionBuildError(f"Cache base de rollback corrupte: {target}")

        blocked = self._inside("/var/lib/xaac-update/blocked-versions.json")
        self._atomic_write(
            blocked,
            json.dumps({"schema_version": 1, "blocked": []}, indent=2, sort_keys=True) + "\n",
            0o640,
        )

        # A production release key is deliberately never generated here. If a
        # real public keyring is supplied by release engineering, copy it into
        # the immutable image. Otherwise update verification remains fail-closed.
        keyring_source = self.paths.project_root / "assets/release/xaac-archive-keyring.gpg"
        if keyring_source.is_file():
            keyring_target = self._inside(model_plan.profile["manifest"]["keyring"])
            keyring_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(keyring_source, keyring_target)
            keyring_target.chmod(0o644)

        if self.dry_run:
            return
        self._chroot(["systemd-tmpfiles", "--create", "/usr/lib/tmpfiles.d/xaac-update.conf"], phase="configure-update-tmpfiles")
        self._chroot(["systemctl", "enable", "xaac-update-recover.service"], phase="configure-update-recovery-service")
        self._chroot(
            [
                "/bin/sh",
                "-ec",
                "test -r /etc/xaac/update/policy.json; "
                "test -r /etc/xaac/update/transactional-installation.json; "
                "test -r /etc/xaac/update/package-rollback.json; "
                "test -r /var/lib/xaac-update/state.json; "
                "test -r /var/lib/xaac-update/transaction-state.json; "
                "test -r /var/lib/xaac-update/rollback-state.json; "
                "test -r /usr/share/xaac/update/current-release.json; "
                "test -x /usr/local/sbin/xaac-update-admin; "
                "test -r /usr/local/libexec/xaac_update_runtime.py; "
                "/usr/bin/python3 -m py_compile /usr/local/sbin/xaac-update-admin /usr/local/libexec/xaac_update_runtime.py; "
                "/usr/local/sbin/xaac-update-admin --help >/dev/null; "
                "systemctl is-enabled --quiet xaac-update-recover.service; "
                "test \"$(stat -c '%a' /usr/local/sbin/xaac-update-admin)\" = '750'; "
                "test \"$(stat -c '%a' /usr/local/libexec/xaac_update_runtime.py)\" = '640'; "
                "test \"$(stat -c '%a' /var/lib/xaac-update/package-cache)\" = '700'",
            ],
            phase="configure-update-architecture-10-2",
        )

    def _configure_base_os_updates(self) -> None:
        """Install the controlled Debian 13 base-system updater (phase 10.6)."""
        try:
            plan = create_base_os_update_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/base-os-update.yaml",
            )
            BaseOsUpdateInstaller().install(plan)
        except BaseOsUpdateError as exc:
            raise ProductionBuildError(
                f"Actualització controlada del sistema base 10.6 invàlida: {exc}"
            ) from exc

        runtime_source = self.paths.project_root / "assets/runtime/xaac_base_os_update_runtime.py"
        if not runtime_source.is_file():
            raise ProductionBuildError("Falta assets/runtime/xaac_base_os_update_runtime.py")
        runtime_target = plan.output("runtime")
        runtime_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime_source, runtime_target)
        runtime_target.chmod(0o640)

        if self.dry_run:
            return
        self._chroot(
            [
                "/bin/sh",
                "-ec",
                "test -r /etc/xaac/update/base-os-policy.json; "
                "test -r /var/lib/xaac-update/base-os-state.json; "
                "test -d /var/lib/xaac-update/base-os-checkpoint; "
                "test \"$(stat -c '%a' /var/lib/xaac-update/base-os-checkpoint)\" = '700'; "
                "test -r /etc/apt/preferences.d/99xaac-base-os-protected; "
                "test -r /etc/apt/apt.conf.d/99xaac-base-os-update; "
                "test -r /usr/local/libexec/xaac_base_os_update_runtime.py; "
                "/usr/bin/python3 -m py_compile /usr/local/libexec/xaac_base_os_update_runtime.py; "
                "/usr/local/sbin/xaac-update-admin --help | grep -F 'os-update' >/dev/null; "
                "grep -F 'Pin-Priority: -1' /etc/apt/preferences.d/99xaac-base-os-protected >/dev/null; "
                "grep -F 'AllowUnauthenticated \"false\"' /etc/apt/apt.conf.d/99xaac-base-os-update >/dev/null; "
                "test -s /usr/share/keyrings/debian-archive-keyring.gpg; "
                "test \"$(systemctl is-enabled apt-daily.timer 2>/dev/null || true)\" = masked; "
                "test \"$(systemctl is-enabled apt-daily-upgrade.timer 2>/dev/null || true)\" = masked",
            ],
            phase="configure-base-os-update-10-6",
        )

    def _configure_maintenance_diagnostics(self) -> None:
        """Install the phase 10.3 maintenance and sanitized diagnostics runtime."""
        try:
            plan = create_maintenance_diagnostics_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/maintenance-diagnostics.yaml",
            )
            MaintenanceDiagnosticsInstaller().install(plan)
        except MaintenanceDiagnosticsError as exc:
            raise ProductionBuildError(
                f"Manteniment i diagnòstic 10.3 invàlids: {exc}"
            ) from exc

        admin_source = self.paths.project_root / "assets/runtime/xaac-maintenance"
        runtime_source = self.paths.project_root / "assets/runtime/xaac_maintenance_runtime.py"
        if not admin_source.is_file():
            raise ProductionBuildError("Falta assets/runtime/xaac-maintenance")
        if not runtime_source.is_file():
            raise ProductionBuildError("Falta assets/runtime/xaac_maintenance_runtime.py")

        admin_target = plan.output("admin")
        runtime_target = plan.output("runtime")
        admin_target.parent.mkdir(parents=True, exist_ok=True)
        runtime_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(admin_source, admin_target)
        shutil.copy2(runtime_source, runtime_target)
        admin_target.chmod(0o750)
        runtime_target.chmod(0o640)

        if self.dry_run:
            return
        self._chroot(
            ["systemd-tmpfiles", "--create", "/usr/lib/tmpfiles.d/xaac-maintenance.conf"],
            phase="configure-maintenance-tmpfiles",
        )
        self._chroot(
            [
                "/bin/sh",
                "-ec",
                "test -r /etc/xaac/maintenance/policy.json; "
                "test -r /var/lib/xaac-maintenance/state.json; "
                "test -d /var/lib/xaac-maintenance/diagnostics; "
                "test -x /usr/local/sbin/xaac-maintenance; "
                "test -r /usr/local/libexec/xaac_maintenance_runtime.py; "
                "/usr/bin/python3 -m py_compile "
                "/usr/local/sbin/xaac-maintenance "
                "/usr/local/libexec/xaac_maintenance_runtime.py; "
                "/usr/local/sbin/xaac-maintenance --help >/dev/null; "
                "test \"$(stat -c '%a' /usr/local/sbin/xaac-maintenance)\" = '750'; "
                "test \"$(stat -c '%a' /usr/local/libexec/xaac_maintenance_runtime.py)\" = '640'; "
                "test \"$(stat -c '%a' /var/lib/xaac-maintenance/diagnostics)\" = '700'",
            ],
            phase="configure-maintenance-diagnostics-10-3",
        )

    def _configure_recovery_environment(self) -> None:
        """Install the phase 10.4 local boot recovery environment."""
        try:
            plan = create_recovery_environment_plan(
                self.paths.rootfs,
                self.paths.project_root / "config/recovery-environment.yaml",
            )
            RecoveryEnvironmentInstaller().install(plan)
        except RecoveryEnvironmentError as exc:
            raise ProductionBuildError(
                f"Entorn de recuperació 10.4 invàlid: {exc}"
            ) from exc

        admin_source = self.paths.project_root / "assets/runtime/xaac-recovery"
        runtime_source = self.paths.project_root / "assets/runtime/xaac_recovery_runtime.py"
        if not admin_source.is_file():
            raise ProductionBuildError("Falta assets/runtime/xaac-recovery")
        if not runtime_source.is_file():
            raise ProductionBuildError("Falta assets/runtime/xaac_recovery_runtime.py")

        admin_target = plan.output("admin")
        runtime_target = plan.output("runtime")
        admin_target.parent.mkdir(parents=True, exist_ok=True)
        runtime_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(admin_source, admin_target)
        shutil.copy2(runtime_source, runtime_target)
        admin_target.chmod(0o750)
        runtime_target.chmod(0o640)

        self._atomic_write(
            self._inside("/etc/profile.d/xaac-recovery-hint.sh"),
            "# Managed by XAAC Thin Client OS phase 10.4\n"
            "if [ \"$(id -un 2>/dev/null)\" = xaac-admin ] && [ -t 0 ] && "
            "grep -qw 'systemd.unit=xaac-recovery.target' /proc/cmdline 2>/dev/null; then\n"
            "  printf '%s\\n' 'XAAC Recovery actiu. Executeu: sudo xaac-recovery menu'\n"
            "fi\n",
            0o644,
        )

        if self.dry_run:
            return
        self._chroot(
            ["systemd-tmpfiles", "--create", "/usr/lib/tmpfiles.d/xaac-recovery.conf"],
            phase="configure-recovery-tmpfiles",
        )
        self._chroot(
            [
                "/bin/sh",
                "-ec",
                "test -r /etc/xaac/recovery/policy.json; "
                "test -r /var/lib/xaac-recovery/state.json; "
                "test -x /usr/local/sbin/xaac-recovery; "
                "test -r /usr/local/libexec/xaac_recovery_runtime.py; "
                "test -f /etc/systemd/system/xaac-recovery.target; "
                "test -f /etc/systemd/system/xaac-recovery-console.service; "
                "test ! -e /usr/local/libexec/xaac/recovery-admin-login; "
                "test -x /etc/grub.d/42_xaac_recovery; "
                "test -f /etc/default/grub.d/99-xaac-recovery.cfg; "
                "grep -Fx 'GRUB_TIMEOUT=1' /etc/default/grub.d/99-xaac-recovery.cfg >/dev/null; "
                "grep -F 'systemd.unit=xaac-recovery.target' /etc/grub.d/42_xaac_recovery >/dev/null; "
                "grep -F 'Conflicts=graphical.target greetd.service xaac-vpn-manager.service xaac-agent.service' "
                "/etc/systemd/system/xaac-recovery.target >/dev/null; "
                "grep -F 'Wants=systemd-user-sessions.service keyboard-setup.service console-setup.service xaac-recovery-console.service' "
                "/etc/systemd/system/xaac-recovery.target >/dev/null; "
                "grep -F 'ExecStart=-/sbin/agetty -o ' /etc/systemd/system/xaac-recovery-console.service >/dev/null; "
                "grep -F -- '--noissue - linux' /etc/systemd/system/xaac-recovery-console.service >/dev/null; "
                "! grep -F -- '--noreset' /etc/systemd/system/xaac-recovery-console.service >/dev/null; "
                "! grep -F -- '--noclear' /etc/systemd/system/xaac-recovery-console.service >/dev/null; "
                "grep -F 'ExecStartPre=-/bin/setupcon --keyboard-only --force' /etc/systemd/system/xaac-recovery-console.service >/dev/null; "
                "grep -F \"ExecStartPre=-/bin/sh -c 'stty sane < /dev/tty1'\" /etc/systemd/system/xaac-recovery-console.service >/dev/null; "
                "! grep -F -- '--login-program' /etc/systemd/system/xaac-recovery-console.service >/dev/null; "
                "TERM=linux /usr/bin/systemd-analyze verify /etc/systemd/system/xaac-recovery-console.service >/dev/null 2>&1; "
                "/usr/bin/python3 -m py_compile /usr/local/sbin/xaac-recovery "
                "/usr/local/libexec/xaac_recovery_runtime.py; "
                "/bin/sh -n /etc/grub.d/42_xaac_recovery; "
                "/usr/local/sbin/xaac-recovery --help >/dev/null; "
                "test \"$(stat -c '%a' /usr/local/sbin/xaac-recovery)\" = '750'; "
                "test \"$(stat -c '%a' /usr/local/libexec/xaac_recovery_runtime.py)\" = '640'",
            ],
            phase="configure-recovery-environment-10-4",
        )

    def _configure_openvpn3_network(self) -> None:
        """Persist the OpenVPN 3 DNS backend used by the minimal XAAC OS.

        XAAC Thin Client OS uses NetworkManager with a normal /etc/resolv.conf
        and does not enable systemd-resolved.  OpenVPN 3 must therefore use its
        ResolvConfFile backend, matching the configuration validated on the
        target terminal.
        """
        self._chroot(
            [
                "/bin/sh", "-ec",
                # init-config works offline in the build chroot and writes the
                # netcfg configuration directly.  Do not call
                # `openvpn3-admin netcfg-service` here: that management
                # command requires the net.openvpn.v3.netcfg D-Bus service,
                # which intentionally is not running inside the ISO chroot.
                "openvpn3-admin init-config --write-configs --force; "
                "test -s /var/lib/openvpn3/netcfg.json; "
                "grep -F '/etc/resolv.conf' /var/lib/openvpn3/netcfg.json >/dev/null",
            ],
            phase="configure-openvpn3-netcfg",
        )

    def _install_zorin_icon_theme(self) -> None:
        """Install the minimal exact ZorinBlue-Light icon subset used by XAAC.

        The project vendors only the icons referenced directly by XAAC Thin
        Client.  Their SVG contents and symbolic aliases come from the exact
        effective Zorin development theme.  Keeping the original icon name,
        category and alias target makes GTK lookup deterministic while the
        standard Adwaita/gnome/hicolor inheritance remains available for GTK
        internal icons.
        """
        source = self.paths.project_root / "assets/zorin-icons/XAAC-Zorin-Light"
        if not (source / "index.theme").is_file():
            raise ProductionBuildError(
                "Falta assets/zorin-icons/XAAC-Zorin-Light/index.theme"
            )
        destination = self._inside("/usr/share/icons/XAAC-Zorin-Light")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=False)
        self._chroot([
            "/bin/sh", "-c",
            "command -v gtk-update-icon-cache >/dev/null 2>&1 && "
            "gtk-update-icon-cache -f /usr/share/icons/XAAC-Zorin-Light "
            ">/dev/null 2>&1 || true",
        ], phase="configure-zorin-icon-cache")

    def _install_zorin_gtk_theme(self) -> None:
        """Install the exact ZorinBlue-Light GTK snapshot from development."""
        source = self.paths.project_root / "assets/zorin-theme/ZorinBlue-Light"
        if not (source / "index.theme").is_file():
            raise ProductionBuildError("Falta assets/zorin-theme/ZorinBlue-Light/index.theme")
        for subdir in ("gtk-3.0", "gtk-4.0"):
            if not (source / subdir / "gtk.css").is_file():
                raise ProductionBuildError(f"Falta el tema GTK exportat: {subdir}/gtk.css")
        destination = self._inside("/usr/share/themes/ZorinBlue-Light")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=False)

    def _customize_xaac_thinclient_theme(self) -> None:
        """Apply the XAAC OS visual baseline to the packaged GTK client."""
        css = self._inside("/usr/lib/python3/dist-packages/xaac_thinclient/resources/style.css")
        if not css.is_file():
            raise ProductionBuildError("No s’ha trobat el full d’estils de XAAC Thin Client")
        content = css.read_text(encoding="utf-8")
        if ".application-background" not in content:
            raise ProductionBuildError("El full d’estils de XAAC Thin Client no conté application-background")
        content = content.replace("background: #e8eef5;", "background: #dce4ed;", 1)
        if 'font-family: "Roboto";' not in content:
            content = '* {\n    font-family: "Roboto";\n}\n\n' + content
        self._atomic_write(css, content, 0o644)

    def _configure_xaac_thinclient_production_runtime(self) -> None:
        """Bind the generic XAAC Thin Client package to the OS kiosk runtime.

        The Debian package deliberately defaults to development mode.  The OS
        must opt in explicitly to production semantics so the footer power
        action shuts down the terminal instead of merely quitting the client.
        Privileged power actions are exposed through two fixed root-owned
        helpers and an exact sudoers allow-list; xaac-kiosk receives no general
        sudo capability.
        """
        config = self._inside("/etc/xaac-thinclient/config.ini")
        if not config.is_file():
            raise ProductionBuildError("Falta /etc/xaac-thinclient/config.ini")
        content = config.read_text(encoding="utf-8")
        if "mode = development" not in content:
            if "mode = production" not in content:
                raise ProductionBuildError("No s’ha pogut determinar application.mode de XAAC Thin Client")
        else:
            content = content.replace("mode = development", "mode = production", 1)
            self._atomic_write(config, content, 0o644)

        transition_launcher = r'''#!/bin/sh
set -eu
action=${1:-}
case "$action" in poweroff|reboot) ;; *) exit 64 ;; esac

kiosk_user=xaac-kiosk
kiosk_uid=$(/usr/bin/id -u "$kiosk_user")
runtime_dir=/run/user/$kiosk_uid
ready_file=$runtime_dir/xaac-power-transition.ready
pid_file=/run/xaac-power-transition.pid
screen=/usr/local/libexec/xaac-power-transition

# Prepare tty1 as an XAAC-neutral granite fallback canvas in case the compositor vanishes
# before Plymouth takes ownership of the framebuffer.
printf '\033[?25l\033[37;100m\033[2J\033[H\033[3J' > /dev/tty1 2>/dev/null || true
rm -f "$ready_file" "$pid_file"
[ -x "$screen" ] || exit 0
[ -d "$runtime_dir" ] || exit 0

wayland_display=
for socket in "$runtime_dir"/wayland-*; do
    if [ -S "$socket" ]; then
        wayland_display=${socket##*/}
        break
    fi
done

display=${DISPLAY:-}
if [ -z "$display" ] && [ -S /tmp/.X11-unix/X0 ]; then
    display=:0
fi

if [ -n "$wayland_display" ]; then
    backend=wayland
elif [ -n "$display" ]; then
    backend=x11
else
    exit 0
fi

set -- /usr/bin/env \
    "HOME=/home/$kiosk_user" \
    "USER=$kiosk_user" \
    "LOGNAME=$kiosk_user" \
    "XDG_RUNTIME_DIR=$runtime_dir" \
    "GDK_BACKEND=$backend"
[ -n "$wayland_display" ] && set -- "$@" "WAYLAND_DISPLAY=$wayland_display"
[ -n "$display" ] && set -- "$@" "DISPLAY=$display"
[ -S "$runtime_dir/bus" ] && set -- "$@" "DBUS_SESSION_BUS_ADDRESS=unix:path=$runtime_dir/bus"

/usr/sbin/runuser -u "$kiosk_user" -- "$@" "$screen" "$action" "$ready_file" >/dev/null 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$pid_file"

# Bound the handoff: power actions must never depend on GTK becoming ready.
steps=0
while [ ! -f "$ready_file" ] && kill -0 "$pid" 2>/dev/null && [ "$steps" -lt 20 ]; do
    sleep 0.1
    steps=$((steps + 1))
done
exit 0
'''
        transition_stop = r'''#!/bin/sh
set -u
pid_file=/run/xaac-power-transition.pid
if [ -r "$pid_file" ]; then
    pid=$(cat "$pid_file" 2>/dev/null || true)
    case "$pid" in *[!0-9]*|'') ;; *) kill "$pid" 2>/dev/null || true ;; esac
fi
rm -f "$pid_file" /run/user/*/xaac-power-transition.ready 2>/dev/null || true
exit 0
'''
        self._atomic_write(
            self._inside("/usr/local/libexec/xaac/start-power-transition"),
            transition_launcher,
            0o755,
        )
        self._atomic_write(
            self._inside("/usr/local/libexec/xaac/stop-power-transition"),
            transition_stop,
            0o755,
        )
        self._atomic_write(
            self._inside("/usr/local/sbin/xaac-kiosk-poweroff"),
            "#!/bin/sh\n"
            "set -u\n"
            "/usr/local/libexec/xaac/start-power-transition poweroff || true\n"
            "/usr/bin/systemctl poweroff\n"
            "rc=$?\n"
            "[ \"$rc\" -eq 0 ] || /usr/local/libexec/xaac/stop-power-transition\n"
            "exit \"$rc\"\n",
            0o755,
        )
        self._atomic_write(
            self._inside("/usr/local/sbin/xaac-kiosk-reboot"),
            "#!/bin/sh\n"
            "set -u\n"
            "/usr/local/libexec/xaac/start-power-transition reboot || true\n"
            "/usr/bin/systemctl reboot\n"
            "rc=$?\n"
            "[ \"$rc\" -eq 0 ] || /usr/local/libexec/xaac/stop-power-transition\n"
            "exit \"$rc\"\n",
            0o755,
        )
        self._atomic_write(
            self._inside("/etc/sudoers.d/xaac-kiosk-power"),
            "Defaults:xaac-kiosk use_pty\n"
            "xaac-kiosk ALL=(root) NOPASSWD: /usr/local/sbin/xaac-kiosk-poweroff, "
            "/usr/local/sbin/xaac-kiosk-reboot\n",
            0o440,
        )

    def _configure_freerdp_certificate_store(self) -> None:
        """Create the persistent FreeRDP certificate store for xaac-kiosk.

        FreeRDP strict certificate checking expects per-server PEM files under
        /etc/xaac/freerdp/server.  The directory must exist before the first RDP
        connection and must survive reboot, otherwise FreeRDP reports BIO_new
        failures and rejects the server with ERRCONNECT_TLS_CONNECT_FAILED.
        """
        tmpfiles = self._inside("/usr/lib/tmpfiles.d/xaac-freerdp.conf")
        self._atomic_write(
            tmpfiles,
            "# XAAC Thin Client OS - persistent FreeRDP certificate store\n"
            "d /etc/xaac/freerdp 0700 xaac-kiosk xaac-kiosk -\n"
            "d /etc/xaac/freerdp/server 0700 xaac-kiosk xaac-kiosk -\n",
            0o644,
        )
        self._chroot(
            [
                "/usr/bin/install", "-d", "-m", "0700",
                "-o", "xaac-kiosk", "-g", "xaac-kiosk",
                "/etc/xaac/freerdp", "/etc/xaac/freerdp/server",
            ],
            phase="configure-freerdp-certificate-store",
        )

    def _configure_tty_cursor_visibility(self) -> None:
        """Restore a visible text cursor whenever an authenticated getty starts.

        The kernel keeps ``vt.global_cursor_default=0`` so tty1 remains visually
        clean during Plymouth/greetd startup.  A getty-specific drop-in then
        re-enables DECTCEM on text consoles, so tty2..tty6 and the administrative
        TTY have a normal cursor for editing commands.
        """
        self._atomic_write(
            self._inside("/usr/local/libexec/xaac/show-tty-cursor"),
            "#!/bin/sh\n"
            "set -eu\n"
            "tty_name=${1:-}\n"
            "case $tty_name in tty[0-9]|tty1[0-2]) ;; *) exit 2 ;; esac\n"
            "printf '\\033[?25h' > \"/dev/$tty_name\"\n",
            0o755,
        )
        self._atomic_write(
            self._inside("/etc/systemd/system/getty@.service.d/20-xaac-visible-cursor.conf"),
            "[Service]\n"
            "ExecStartPre=/usr/local/libexec/xaac/show-tty-cursor %I\n",
            0o644,
        )
        self._atomic_write(
            self._inside("/etc/profile.d/20-xaac-visible-tty-cursor.sh"),
            "# XAAC Thin Client OS - keep text-console cursor visible\n"
            "case $(/usr/bin/tty 2>/dev/null || true) in\n"
            "    /dev/tty[2-9]|/dev/tty1[0-2]) printf '\\033[?25h' ;;\n"
            "esac\n",
            0o644,
        )

    def _configure_boot_splash(self) -> None:
        """Install the XAAC Plymouth theme and silent installed-system boot policy."""
        source = self.paths.project_root / "assets/branding/XAAC_TC_OS.png"
        if not source.is_file():
            raise ProductionBuildError("Falta assets/branding/XAAC_TC_OS.png")
        kernel_cmdline = " ".join(self.settings.kernel_parameters)

        # Load Intel KMS from the initramfs so Plymouth can acquire DRM as early
        # as possible on the Wyse 3040.  This shortens the unavoidable blank
        # interval between firmware/GRUB and the first branded userspace frame.
        initramfs_modules = self._inside("/etc/initramfs-tools/modules")
        existing_modules = initramfs_modules.read_text(encoding="utf-8") if initramfs_modules.exists() else ""
        if "i915" not in {line.strip() for line in existing_modules.splitlines()}:
            early_modules = existing_modules.rstrip() + ("\n" if existing_modules.strip() else "") + "i915\n"
            self._atomic_write(initramfs_modules, early_modules)
        self._atomic_write(
            self._inside("/etc/modules-load.d/xaac-intel-graphics.conf"),
            "# XAAC Thin Client OS - Intel graphics / early KMS\ni915\n",
        )

        theme_dir = self._inside("/usr/share/plymouth/themes/xaac")
        theme_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, theme_dir / "XAAC_TC_OS.png")
        for index in range(3):
            spinner_source = self.paths.project_root / f"assets/branding/XAAC_loading_{index}.png"
            if not spinner_source.is_file():
                raise ProductionBuildError(f"Falta {spinner_source.relative_to(self.paths.project_root)}")
            shutil.copy2(spinner_source, theme_dir / spinner_source.name)
        self._atomic_write(
            theme_dir / "xaac.plymouth",
            "[Plymouth Theme]\n"
            "Name=XAAC Thin Client OS\n"
            "Description=XAAC Thin Client OS boot and shutdown splash\n"
            "ModuleName=script\n\n"
            "[script]\n"
            "ImageDir=/usr/share/plymouth/themes/xaac\n"
            "ScriptFile=/usr/share/plymouth/themes/xaac/xaac.script\n",
        )
        self._atomic_write(
            theme_dir / "xaac.script",
            "Window.SetBackgroundTopColor(0.35, 0.38, 0.40);\n"
            "Window.SetBackgroundBottomColor(0.35, 0.38, 0.40);\n\n"
            "screen_width = Window.GetWidth();\n"
            "screen_height = Window.GetHeight();\n"
            "image = Image(\"XAAC_TC_OS.png\");\n"
            "image_width = image.GetWidth();\n"
            "image_height = image.GetHeight();\n"
            "scale_x = screen_width / image_width;\n"
            "scale_y = screen_height / image_height;\n"
            "scale = scale_x;\n"
            "if (scale_y > scale_x)\n"
            "  scale = scale_y;\n"
            "scaled_width = image_width * scale;\n"
            "scaled_height = image_height * scale;\n"
            "image = image.Scale(scaled_width, scaled_height);\n"
            "sprite = Sprite(image);\n"
            "sprite.SetX((screen_width - scaled_width) / 2);\n"
            "sprite.SetY((screen_height - scaled_height) / 2);\n"
            "sprite.SetZ(10000);\n\n"
            "spinner_image_0 = Image(\"XAAC_loading_0.png\");\n"
            "spinner_image_1 = Image(\"XAAC_loading_1.png\");\n"
            "spinner_image_2 = Image(\"XAAC_loading_2.png\");\n"
            "spinner = Sprite(spinner_image_0);\n"
            "spinner.SetX((screen_width - spinner_image_0.GetWidth()) / 2);\n"
            "spinner.SetY(screen_height - spinner_image_0.GetHeight() - 40);\n"
            "spinner.SetZ(10001);\n"
            "spinner_frame = 0;\n"
            "spinner_tick = 0;\n"
            "fun refresh_callback() {\n"
            "  spinner_tick++;\n"
            "  if (spinner_tick >= 6) {\n"
            "    spinner_tick = 0;\n"
            "    spinner_frame++;\n"
            "    if (spinner_frame >= 3) spinner_frame = 0;\n"
            "    if (spinner_frame == 0) spinner.SetImage(spinner_image_0);\n"
            "    if (spinner_frame == 1) spinner.SetImage(spinner_image_1);\n"
            "    if (spinner_frame == 2) spinner.SetImage(spinner_image_2);\n"
            "  }\n"
            "}\n"
            "Plymouth.SetRefreshRate(20);\n"
            "Plymouth.SetRefreshFunction(refresh_callback);\n",
        )

        self._atomic_write(
            self._inside("/etc/systemd/system/xaac-clear-console-before-shutdown.service"),
            "[Unit]\n"
            "Description=XAAC clear console before Plymouth shutdown splash\n"
            "DefaultDependencies=no\n"
            "Before=plymouth-poweroff.service plymouth-reboot.service plymouth-halt.service "
            "systemd-poweroff.service systemd-reboot.service systemd-halt.service\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/bin/sh -c 'printf \"\\033[?25l\\033[37;100m\\033[2J\\033[H\\033[3J\" > /dev/tty1'\n\n"
            "[Install]\n"
            "WantedBy=poweroff.target reboot.target halt.target\n",
            0o644,
        )
        self._chroot(
            ["systemctl", "enable", "xaac-clear-console-before-shutdown.service"],
            phase="configure-shutdown-console-cleanup",
        )

        self._atomic_write(
            self._inside("/etc/default/grub.d/20-xaac-visual.cfg"),
            '# XAAC Thin Client OS - silent graphical boot\n'
            'GRUB_TIMEOUT=0\n'
            'GRUB_TIMEOUT_STYLE=hidden\n'
            'GRUB_RECORDFAIL_TIMEOUT=0\n'
            'GRUB_DISABLE_RECOVERY=true\n'
            'GRUB_DISABLE_OS_PROBER=true\n'
            'GRUB_GFXPAYLOAD_LINUX=keep\n'
            f'GRUB_CMDLINE_LINUX_DEFAULT="{kernel_cmdline}"\n',
        )
        self._chroot(["plymouth-set-default-theme", "xaac"], phase="configure-plymouth-theme")

    def phase_configure(self) -> None:
        self._require_root()
        if not (self.paths.rootfs / "etc/debian_version").is_file():
            raise ProductionBuildError("El rootfs no existeix; executa primer la fase rootfs")

        self._write_apt_sources()
        self._prepare_chroot_network()
        self._atomic_write(self._inside("/usr/sbin/policy-rc.d"), "#!/bin/sh\nexit 101\n", 0o755)
        self._atomic_write(self._inside("/etc/hostname"), self.settings.hostname + "\n")
        self._atomic_write(
            self._inside("/etc/hosts"),
            "127.0.0.1\tlocalhost\n127.0.1.1\t" + self.settings.hostname + "\n"
            "::1\tlocalhost ip6-localhost ip6-loopback\n",
        )
        locales = (self.settings.locale, *self.settings.fallback_locales)
        self._atomic_write(
            self._inside("/etc/locale.gen"),
            "".join(f"{locale} UTF-8\n" for locale in dict.fromkeys(locales)),
        )
        self._atomic_write(self._inside("/etc/default/locale"), f"LANG={self.settings.locale}\n")
        self._atomic_write(
            self._inside("/etc/default/keyboard"),
            f'XKBMODEL="pc105"\nXKBLAYOUT="{self.settings.keyboard_layout}"\n'
            f'XKBVARIANT="{self.settings.keyboard_variant}"\nXKBOPTIONS=""\n',
        )
        timezone_path = self._inside("/etc/timezone")
        self._atomic_write(timezone_path, self.settings.timezone + "\n")
        localtime = self._inside("/etc/localtime")
        with contextlib.suppress(FileNotFoundError):
            localtime.unlink()
        localtime.symlink_to(f"/usr/share/zoneinfo/{self.settings.timezone}")

        build_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        os_release = (
            "NAME=\"XAAC Thin Client OS\"\n"
            f"VERSION=\"{self.settings.version}\"\n"
            "ID=xaac-thin-client-os\nID_LIKE=debian\n"
            f"VERSION_ID=\"{self.settings.version}\"\n"
            f"PRETTY_NAME=\"XAAC Thin Client OS {self.settings.version}\"\n"
            f"XAAC_PROFILE=\"{self.settings.profile}\"\nXAAC_BUILD_ID=\"{build_id}\"\n"
        )
        self._atomic_write(self._inside("/etc/os-release"), os_release)
        self._atomic_write(self._inside("/etc/xaac/os-release"), os_release)
        self._atomic_write(self._inside("/etc/issue"), f"XAAC Thin Client OS {self.settings.version} \\n \\l\n")
        self._atomic_write(self._inside("/etc/issue.net"), f"XAAC Thin Client OS {self.settings.version}\n")
        self._atomic_write(self._inside("/etc/motd"), "XAAC Thin Client OS\nAdministració local restringida a personal autoritzat.\n")
        self._atomic_write(
            self._inside("/etc/default/xaac-os"),
            f'XAAC_OS_VERSION="{self.settings.version}"\n'
            f'XAAC_OS_PROFILE="{self.settings.profile}"\n'
            f'XAAC_OS_BUILD_ID="{build_id}"\n',
        )
        if self.settings.channel == "development":
            self._atomic_write(
                self._inside("/etc/xaac/development-mode"),
                f"channel={self.settings.channel}\nbuild_id={build_id}\n",
                0o644,
            )
            self._atomic_write(
                self._inside("/usr/local/libexec/xaac/diagnostics"),
                DEVELOPMENT_DIAGNOSTICS_SCRIPT,
                0o755,
            )
            self._atomic_write(
                self._inside("/etc/sudoers.d/xaac-kiosk-diagnostics"),
                "Defaults!/usr/local/libexec/xaac/diagnostics !authenticate,use_pty\n"
                "xaac-kiosk ALL=(root) NOPASSWD: /usr/local/libexec/xaac/diagnostics, "
                "/usr/local/libexec/xaac/diagnostics --pam-test\n",
                0o440,
            )
        # XAAC owns the complete console policy. Remove any stale Debian Live
        # autologin artefact left by an incremental build. tty2..tty6 deliberately
        # use Debian's untouched authenticated getty@.service template.
        for stale in (
            "/etc/systemd/system/getty@.service.d/autologin.conf",
            "/etc/systemd/system/getty@.service.d/live-config_autologin.conf",
            "/etc/live/config.conf.d/xaac.conf",
            *(f"/etc/systemd/system/getty@tty{tty}.service.d/99-xaac-authenticated.conf" for tty in range(2, 7)),
        ):
            with contextlib.suppress(FileNotFoundError):
                self._inside(stale).unlink()
        self._configure_tty_cursor_visibility()
        installed_kernel_cmdline = " ".join(self.settings.kernel_parameters)
        self._atomic_write(
            self._inside("/usr/local/sbin/xaac-installer-welcome"),
            (
                "#!/bin/sh\n"
                "set -eu\n"
                "export LANG=C.UTF-8\n"
                "export LC_ALL=C.UTF-8\n"
                "if command -v setupcon >/dev/null 2>&1; then setupcon --force >/dev/null 2>&1 || true; fi\n"
                "printf '\\033[?25h'\n"
                "setterm --cursor on >/dev/null 2>&1 || true\n"
                "xaac_msg() {\n"
                "    key=$1\n"
                "    case \"${install_language:-ca}:$key\" in\n"
                "        ca:admin_activate_fail) printf '%s' 'No ha sigut possible activar la contrasenya de xaac-admin.' ;;\n"
                "        ca:admin_altered) printf '%s' 'La verificació final ha detectat que xaac-admin ha tornat a quedar bloquejat o alterat.' ;;\n"
                "        ca:admin_hash_fail) printf '%s' 'El hash de xaac-admin no ha quedat escrit al sistema de destinació.' ;;\n"
                "        ca:admin_ok) printf '%s' 'Contrasenya administrativa validada. Comença la instal·lació.' ;;\n"
                "        ca:admin_shell_fail) printf '%s' 'La shell de xaac-admin no és interactiva.' ;;\n"
                "        ca:all_data) printf '%s' 'Totes les dades d'\\''aquest disc s'\\''eliminaran immediatament després de confirmar.' ;;\n"
                "        ca:block5_missing) printf '%s' 'Falta el marcador d'\\''integració del Bloc 5.' ;;\n"
                "        ca:capacity) printf '%s' 'Capacitat' ;;\n"
                "        ca:complete) printf '%s' 'Instal·lació completada i verificada. El disc ja és arrancable en mode UEFI.' ;;\n"
                "        ca:failure) printf '%s' 'La instal·lació s'\\''ha aturat per una errada. No s'\\''obrirà cap consola de login.' ;;\n"
                "        ca:failure_reboot) printf '%s' 'Premeu Retorn per reiniciar el sistema: ' ;;\n"
                "        ca:configure_hostname) printf '%s' 'Configureu el nom de la màquina.' ;;\n"
                "        ca:configure_password) printf '%s' 'Configureu ara la contrasenya de l'\\''administrador local xaac-admin.' ;;\n"
                "        ca:configure_rdp) printf '%s' 'Configureu el servidor RDP principal.' ;;\n"
                "        ca:confirm) printf '%s' 'Per confirmar la selecció escriviu exactament: INSTALL XAAC' ;;\n"
                "        ca:confirmation_bad) printf '%s' 'Confirmació incorrecta. No s'\\''ha fet cap canvi.' ;;\n"
                "        ca:confirmation_ok) printf '%s' 'Confirmació acceptada.' ;;\n"
                "        ca:device) printf '%s' 'Dispositiu' ;;\n"
                "        ca:dhcp) printf '%s' 'La xarxa Ethernet es configurarà automàticament per DHCP.' ;;\n"
                "        ca:dhcp_final_fail) printf '%s' 'La xarxa DHCP no ha quedat configurada.' ;;\n"
                "        ca:disk_changed) printf '%s' 'El disc ha canviat des de la detecció.' ;;\n"
                "        ca:disk_missing) printf '%s' 'El disc seleccionat ja no existeix.' ;;\n"
                "        ca:disk_mounted) printf '%s' 'El disc o alguna partició està muntada. Instal·lació rebutjada.' ;;\n"
                "        ca:disk_small) printf '%s' 'El disc és massa petit per instal·lar XAAC Thin Client OS.' ;;\n"
                "        ca:disks) printf '%s' 'Discs detectats:' ;;\n"
                "        ca:esp_invalid) printf '%s' 'La primera partició no és una ESP GPT vàlida.' ;;\n"
                "        ca:fallback_uuid) printf '%s' 'El fallback GRUB no referencia el UUID arrel.' ;;\n"
                "        ca:fat_invalid) printf '%s' 'La partició EFI FAT32 no supera la verificació.' ;;\n"
                "        ca:grub_entry_fail) printf '%s' 'grub.cfg no conté l'\\''entrada XAAC Thin Client OS.' ;;\n"
                "        ca:grub_initrd_fail) printf '%s' 'grub.cfg no conté cap ordre initrd.' ;;\n"
                "        ca:grub_linux_fail) printf '%s' 'grub.cfg no conté cap ordre linux per carregar el nucli.' ;;\n"
                "        ca:grub_signed_missing) printf '%s' 'No es troba grubx64.efi signat.' ;;\n"
                "        ca:grubcfg_fail) printf '%s' 'No ha sigut possible generar grub.cfg.' ;;\n"
                "        ca:hash_fail) printf '%s' 'No ha sigut possible generar el hash SHA-512 de xaac-admin.' ;;\n"
                "        ca:hostname_final_fail) printf '%s' 'El hostname no ha quedat configurat.' ;;\n"
                "        ca:hostname_invalid) printf '%s' 'Hostname no vàlid.' ;;\n"
                "        ca:hostname_long) printf '%s' 'Hostname massa llarg.' ;;\n"
                "        ca:hostname_prompt) printf '%s' 'Hostname [xaac-thin-client]: ' ;;\n"
                "        ca:hosts_final_fail) printf '%s' '/etc/hosts no conté el hostname.' ;;\n"
                "        ca:identity_fail) printf '%s' 'La identitat del sistema instal·lat no és correcta.' ;;\n"
                "        ca:initrd_live_missing) printf '%s' 'No es troba initramfs del mitjà Live.' ;;\n"
                "        ca:installer_remains) printf '%s' 'El programa instal·lador continua present al sistema instal·lat.' ;;\n"
                "        ca:installer_service_remains) printf '%s' 'El servei del programa instal·lador continua habilitat.' ;;\n"
                "        ca:internal) printf '%s' 'intern' ;;\n"
                "        ca:invalid_option) printf '%s' 'Opció no vàlida.' ;;\n"
                "        ca:invalid_pe) printf '%s' 'No és un executable PE/COFF vàlid:' ;;\n"
                "        ca:invalid_selection) printf '%s' 'Selecció no vàlida.' ;;\n"
                "        ca:invalid_target) printf '%s' 'Dispositiu de destinació no vàlid.' ;;\n"
                "        ca:kernel_copy_fail) printf '%s' 'El nucli o initramfs no han quedat instal·lats a /boot.' ;;\n"
                "        ca:kernel_live_missing) printf '%s' 'No es troba el nucli del mitjà Live.' ;;\n"
                "        ca:kernel_unknown) printf '%s' 'No ha sigut possible determinar la versió del nucli instal·lat.' ;;\n"
                "        ca:keyboard_es) printf '%s' 'Espanyol' ;;\n"
                "        ca:keyboard_final_fail) printf '%s' 'La distribució de teclat seleccionada no ha quedat aplicada.' ;;\n"
                "        ca:keyboard_prompt) printf '%s' 'Seleccioneu la distribució [1]: ' ;;\n"
                "        ca:keyboard_title) printf '%s' 'Distribució del teclat' ;;\n"
                "        ca:keyboard_us) printf '%s' 'English (US)' ;;\n"
                "        ca:kiosk_lock_fail) printf '%s' 'El compte xaac-kiosk ha de romandre bloquejat.' ;;\n"
                "        ca:kiosk_shell_fail) printf '%s' 'xaac-kiosk no pot tindre shell interactiva.' ;;\n"
                "        ca:live_disk) printf '%s' 'El disc seleccionat conté el sistema Live actiu. Instal·lació rebutjada.' ;;\n"
                "        ca:locale_final_fail) printf '%s' 'La configuració regional seleccionada no ha quedat aplicada.' ;;\n"
                "        ca:marker_missing) printf '%s' 'No existeix el marcador de consolidació.' ;;\n"
                "        ca:missing_file) printf '%s' 'No existeix o està buit:' ;;\n"
                "        ca:model) printf '%s' 'Model' ;;\n"
                "        ca:model_unknown) printf '%s' 'Model no informat' ;;\n"
                "        ca:no_ac) printf '%s' 'No s'\\''ha detectat alimentació externa. Instal·lació rebutjada.' ;;\n"
                "        ca:no_disk) printf '%s' 'No s'\\''ha detectat cap disc escrivible.' ;;\n"
                "        ca:out_range) printf '%s' 'Selecció fora de rang.' ;;\n"
                "        ca:package_missing) printf '%s' 'xaac-thinclient 1.0.0 no consta instal·lat.' ;;\n"
                "        ca:pam_fail) printf '%s' 'PAM ha rebutjat la contrasenya de xaac-admin.' ;;\n"
                "        ca:partition_fail) printf '%s' 'No s'\\''ha creat la partició:' ;;\n"
                "        ca:password) printf '%s' 'Contrasenya: ' ;;\n"
                "        ca:password_colon) printf '%s' 'La contrasenya no pot contindre dos punts (:).' ;;\n"
                "        ca:password_mismatch) printf '%s' 'Les contrasenyes no coincideixen.' ;;\n"
                "        ca:password_rules) printf '%s' 'Ha de tindre almenys 12 caràcters i no pot contindre dos punts (:).' ;;\n"
                "        ca:password_short) printf '%s' 'La contrasenya és massa curta.' ;;\n"
                "        ca:poweroff) printf '%s' 'Premeu Retorn per apagar el sistema: ' ;;\n"
                "        ca:preflight) printf '%s' 'Preflight, particionat GPT, format i desplegament del sistema base.' ;;\n"
                "        ca:rdp_domain) printf '%s' 'Domini RDP: ' ;;\n"
                "        ca:rdp_domain_empty) printf '%s' 'El domini RDP no pot estar buit.' ;;\n"
                "        ca:rdp_host) printf '%s' 'Servidor RDP (nom DNS o IP): ' ;;\n"
                "        ca:rdp_host_empty) printf '%s' 'El servidor RDP no pot estar buit.' ;;\n"
                "        ca:rdp_host_invalid) printf '%s' 'Servidor RDP no vàlid.' ;;\n"
                "        ca:reboot) printf '%s' 'Premeu Retorn per reiniciar el sistema: ' ;;\n"
                "        ca:removable) printf '%s' 'extraïble' ;;\n"
                "        ca:removable_warning) printf '%s' 'Advertència: el dispositiu seleccionat està marcat com a extraïble.' ;;\n"
                "        ca:repeat_password) printf '%s' 'Repetiu la contrasenya: ' ;;\n"
                "        ca:root_lock_fail) printf '%s' 'El compte root ha de romandre bloquejat.' ;;\n"
                "        ca:rootfs_missing) printf '%s' 'No s'\\''ha trobat filesystem.squashfs al mitjà Live.' ;;\n"
                "        ca:s1) printf '%s' '[1/10] Creant la taula GPT i les particions...' ;;\n"
                "        ca:s10) printf '%s' '[10/10] Verificant la instal·lació...' ;;\n"
                "        ca:s2) printf '%s' '[2/10] Creant els sistemes de fitxers...' ;;\n"
                "        ca:s3) printf '%s' '[3/10] Muntant la destinació...' ;;\n"
                "        ca:s4) printf '%s' '[4/10] Desplegant el sistema base...' ;;\n"
                "        ca:s5) printf '%s' '[5/10] Instal·lant el nucli i l'\\''initramfs al sistema de destinació...' ;;\n"
                "        ca:s6) printf '%s' '[6/10] Generant la configuració de muntatge...' ;;\n"
                "        ca:s7) printf '%s' '[7/10] Instal·lant GRUB UEFI...' ;;\n"
                "        ca:s8) printf '%s' '[8/10] Configurant l'\\''administrador local...' ;;\n"
                "        ca:s9) printf '%s' '[9/10] Consolidant el sistema instal·lat i preparant el primer arrencament...' ;;\n"
                "        ca:select_disk) printf '%s' 'Seleccioneu el número del disc: ' ;;\n"
                "        ca:shim_missing) printf '%s' 'No es troba shimx64.efi signat.' ;;\n"
                "        ca:ssh_config_fail) printf '%s' 'La configuració OpenSSH instal·lada no és vàlida.' ;;\n"
                "        ca:ssh_key_fail) printf '%s' 'No ha sigut possible generar la host key ED25519 de OpenSSH.' ;;\n"
                "        ca:ssh_pub_fail) printf '%s' 'No ha sigut possible generar la host key pública ED25519 de OpenSSH.' ;;\n"
                "        ca:summary) printf '%s' 'RESUM DE L'\\''OPERACIÓ DESTRUCTIVA' ;;\n"
                "        ca:thinclient_missing) printf '%s' 'XAAC Thin Client no existeix al sistema instal·lat.' ;;\n"
                "        ca:title) printf '%s' 'XAAC Thin Client OS — Instal·lador (pas 5)' ;;\n"
                "        ca:uuid_fail) printf '%s' 'No ha sigut possible obtindre tots els UUID.' ;;\n"
                "        ca:warning) printf '%s' 'ATENCIÓ: aquest pas elimina totes les dades del disc seleccionat.' ;;\n"
                "        es:admin_activate_fail) printf '%s' 'No ha sido posible activar la contraseña de xaac-admin.' ;;\n"
                "        es:admin_altered) printf '%s' 'La verificación final ha detectado que xaac-admin ha vuelto a quedar bloqueado o alterado.' ;;\n"
                "        es:admin_hash_fail) printf '%s' 'El hash de xaac-admin no se ha escrito en el sistema de destino.' ;;\n"
                "        es:admin_ok) printf '%s' 'Contraseña administrativa validada. Comienza la instalación.' ;;\n"
                "        es:admin_shell_fail) printf '%s' 'La shell de xaac-admin no es interactiva.' ;;\n"
                "        es:all_data) printf '%s' 'Todos los datos de este disco se eliminarán inmediatamente después de confirmar.' ;;\n"
                "        es:block5_missing) printf '%s' 'Falta el marcador de integración del Bloque 5.' ;;\n"
                "        es:capacity) printf '%s' 'Capacidad' ;;\n"
                "        es:complete) printf '%s' 'Instalación completada y verificada. El disco ya puede arrancar en modo UEFI.' ;;\n"
                "        es:failure) printf '%s' 'La instalación se ha detenido por un error. No se abrirá ninguna consola de inicio de sesión.' ;;\n"
                "        es:failure_reboot) printf '%s' 'Pulse Intro para reiniciar el sistema: ' ;;\n"
                "        es:configure_hostname) printf '%s' 'Configure el nombre del equipo.' ;;\n"
                "        es:configure_password) printf '%s' 'Configure ahora la contraseña del administrador local xaac-admin.' ;;\n"
                "        es:configure_rdp) printf '%s' 'Configure el servidor RDP principal.' ;;\n"
                "        es:confirm) printf '%s' 'Para confirmar la selección escriba exactamente: INSTALL XAAC' ;;\n"
                "        es:confirmation_bad) printf '%s' 'Confirmación incorrecta. No se ha realizado ningún cambio.' ;;\n"
                "        es:confirmation_ok) printf '%s' 'Confirmación aceptada.' ;;\n"
                "        es:device) printf '%s' 'Dispositivo' ;;\n"
                "        es:dhcp) printf '%s' 'La red Ethernet se configurará automáticamente mediante DHCP.' ;;\n"
                "        es:dhcp_final_fail) printf '%s' 'La red DHCP no ha quedado configurada.' ;;\n"
                "        es:disk_changed) printf '%s' 'El disco ha cambiado desde la detección.' ;;\n"
                "        es:disk_missing) printf '%s' 'El disco seleccionado ya no existe.' ;;\n"
                "        es:disk_mounted) printf '%s' 'El disco o alguna partición está montada. Instalación rechazada.' ;;\n"
                "        es:disk_small) printf '%s' 'El disco es demasiado pequeño para instalar XAAC Thin Client OS.' ;;\n"
                "        es:disks) printf '%s' 'Discos detectados:' ;;\n"
                "        es:esp_invalid) printf '%s' 'La primera partición no es una ESP GPT válida.' ;;\n"
                "        es:fallback_uuid) printf '%s' 'El fallback GRUB no referencia el UUID raíz.' ;;\n"
                "        es:fat_invalid) printf '%s' 'La partición EFI FAT32 no supera la verificación.' ;;\n"
                "        es:grub_entry_fail) printf '%s' 'grub.cfg no contiene la entrada XAAC Thin Client OS.' ;;\n"
                "        es:grub_initrd_fail) printf '%s' 'grub.cfg no contiene ninguna orden initrd.' ;;\n"
                "        es:grub_linux_fail) printf '%s' 'grub.cfg no contiene ninguna orden linux para cargar el kernel.' ;;\n"
                "        es:grub_signed_missing) printf '%s' 'No se encuentra grubx64.efi firmado.' ;;\n"
                "        es:grubcfg_fail) printf '%s' 'No ha sido posible generar grub.cfg.' ;;\n"
                "        es:hash_fail) printf '%s' 'No ha sido posible generar el hash SHA-512 de xaac-admin.' ;;\n"
                "        es:hostname_final_fail) printf '%s' 'El hostname no ha quedado configurado.' ;;\n"
                "        es:hostname_invalid) printf '%s' 'Hostname no válido.' ;;\n"
                "        es:hostname_long) printf '%s' 'Hostname demasiado largo.' ;;\n"
                "        es:hostname_prompt) printf '%s' 'Hostname [xaac-thin-client]: ' ;;\n"
                "        es:hosts_final_fail) printf '%s' '/etc/hosts no contiene el hostname.' ;;\n"
                "        es:identity_fail) printf '%s' 'La identidad del sistema instalado no es correcta.' ;;\n"
                "        es:initrd_live_missing) printf '%s' 'No se encuentra el initramfs del medio Live.' ;;\n"
                "        es:installer_remains) printf '%s' 'El programa instalador continúa presente en el sistema instalado.' ;;\n"
                "        es:installer_service_remains) printf '%s' 'El servicio del programa instalador continúa habilitado.' ;;\n"
                "        es:internal) printf '%s' 'interno' ;;\n"
                "        es:invalid_option) printf '%s' 'Opción no válida.' ;;\n"
                "        es:invalid_pe) printf '%s' 'No es un ejecutable PE/COFF válido:' ;;\n"
                "        es:invalid_selection) printf '%s' 'Selección no válida.' ;;\n"
                "        es:invalid_target) printf '%s' 'Dispositivo de destino no válido.' ;;\n"
                "        es:kernel_copy_fail) printf '%s' 'El kernel o initramfs no han quedado instalados en /boot.' ;;\n"
                "        es:kernel_live_missing) printf '%s' 'No se encuentra el kernel del medio Live.' ;;\n"
                "        es:kernel_unknown) printf '%s' 'No ha sido posible determinar la versión del kernel instalado.' ;;\n"
                "        es:keyboard_es) printf '%s' 'Español' ;;\n"
                "        es:keyboard_final_fail) printf '%s' 'La distribución de teclado seleccionada no ha quedado aplicada.' ;;\n"
                "        es:keyboard_prompt) printf '%s' 'Seleccione la distribución [1]: ' ;;\n"
                "        es:keyboard_title) printf '%s' 'Distribución del teclado' ;;\n"
                "        es:keyboard_us) printf '%s' 'English (US)' ;;\n"
                "        es:kiosk_lock_fail) printf '%s' 'La cuenta xaac-kiosk debe permanecer bloqueada.' ;;\n"
                "        es:kiosk_shell_fail) printf '%s' 'xaac-kiosk no puede tener una shell interactiva.' ;;\n"
                "        es:live_disk) printf '%s' 'El disco seleccionado contiene el sistema Live activo. Instalación rechazada.' ;;\n"
                "        es:locale_final_fail) printf '%s' 'La configuración regional seleccionada no ha quedado aplicada.' ;;\n"
                "        es:marker_missing) printf '%s' 'No existe el marcador de consolidación.' ;;\n"
                "        es:missing_file) printf '%s' 'No existe o está vacío:' ;;\n"
                "        es:model) printf '%s' 'Modelo' ;;\n"
                "        es:model_unknown) printf '%s' 'Modelo no informado' ;;\n"
                "        es:no_ac) printf '%s' 'No se ha detectado alimentación externa. Instalación rechazada.' ;;\n"
                "        es:no_disk) printf '%s' 'No se ha detectado ningún disco escribible.' ;;\n"
                "        es:out_range) printf '%s' 'Selección fuera de rango.' ;;\n"
                "        es:package_missing) printf '%s' 'xaac-thinclient 1.0.0 no consta como instalado.' ;;\n"
                "        es:pam_fail) printf '%s' 'PAM ha rechazado la contraseña de xaac-admin.' ;;\n"
                "        es:partition_fail) printf '%s' 'No se ha creado la partición:' ;;\n"
                "        es:password) printf '%s' 'Contraseña: ' ;;\n"
                "        es:password_colon) printf '%s' 'La contraseña no puede contener dos puntos (:).' ;;\n"
                "        es:password_mismatch) printf '%s' 'Las contraseñas no coinciden.' ;;\n"
                "        es:password_rules) printf '%s' 'Debe tener al menos 12 caracteres y no puede contener dos puntos (:).' ;;\n"
                "        es:password_short) printf '%s' 'La contraseña es demasiado corta.' ;;\n"
                "        es:poweroff) printf '%s' 'Pulse Intro para apagar el sistema: ' ;;\n"
                "        es:preflight) printf '%s' 'Comprobaciones previas, particionado GPT, formateo y despliegue del sistema base.' ;;\n"
                "        es:rdp_domain) printf '%s' 'Dominio RDP: ' ;;\n"
                "        es:rdp_domain_empty) printf '%s' 'El dominio RDP no puede estar vacío.' ;;\n"
                "        es:rdp_host) printf '%s' 'Servidor RDP (nombre DNS o IP): ' ;;\n"
                "        es:rdp_host_empty) printf '%s' 'El servidor RDP no puede estar vacío.' ;;\n"
                "        es:rdp_host_invalid) printf '%s' 'Servidor RDP no válido.' ;;\n"
                "        es:reboot) printf '%s' 'Pulse Intro para reiniciar el sistema: ' ;;\n"
                "        es:removable) printf '%s' 'extraíble' ;;\n"
                "        es:removable_warning) printf '%s' 'Advertencia: el dispositivo seleccionado está marcado como extraíble.' ;;\n"
                "        es:repeat_password) printf '%s' 'Repita la contraseña: ' ;;\n"
                "        es:root_lock_fail) printf '%s' 'La cuenta root debe permanecer bloqueada.' ;;\n"
                "        es:rootfs_missing) printf '%s' 'No se ha encontrado filesystem.squashfs en el medio Live.' ;;\n"
                "        es:s1) printf '%s' '[1/10] Creando la tabla GPT y las particiones...' ;;\n"
                "        es:s10) printf '%s' '[10/10] Verificando la instalación...' ;;\n"
                "        es:s2) printf '%s' '[2/10] Creando los sistemas de archivos...' ;;\n"
                "        es:s3) printf '%s' '[3/10] Montando el destino...' ;;\n"
                "        es:s4) printf '%s' '[4/10] Desplegando el sistema base...' ;;\n"
                "        es:s5) printf '%s' '[5/10] Instalando el kernel y el initramfs en el sistema de destino...' ;;\n"
                "        es:s6) printf '%s' '[6/10] Generando la configuración de montaje...' ;;\n"
                "        es:s7) printf '%s' '[7/10] Instalando GRUB UEFI...' ;;\n"
                "        es:s8) printf '%s' '[8/10] Configurando el administrador local...' ;;\n"
                "        es:s9) printf '%s' '[9/10] Consolidando el sistema instalado y preparando el primer arranque...' ;;\n"
                "        es:select_disk) printf '%s' 'Seleccione el número del disco: ' ;;\n"
                "        es:shim_missing) printf '%s' 'No se encuentra shimx64.efi firmado.' ;;\n"
                "        es:ssh_config_fail) printf '%s' 'La configuración OpenSSH instalada no es válida.' ;;\n"
                "        es:ssh_key_fail) printf '%s' 'No ha sido posible generar la host key ED25519 de OpenSSH.' ;;\n"
                "        es:ssh_pub_fail) printf '%s' 'No ha sido posible generar la host key pública ED25519 de OpenSSH.' ;;\n"
                "        es:summary) printf '%s' 'RESUMEN DE LA OPERACIÓN DESTRUCTIVA' ;;\n"
                "        es:thinclient_missing) printf '%s' 'XAAC Thin Client no existe en el sistema instalado.' ;;\n"
                "        es:title) printf '%s' 'XAAC Thin Client OS — Instalador (paso 5)' ;;\n"
                "        es:uuid_fail) printf '%s' 'No ha sido posible obtener todos los UUID.' ;;\n"
                "        es:warning) printf '%s' 'ATENCIÓN: este paso elimina todos los datos del disco seleccionado.' ;;\n"
                "        en:admin_activate_fail) printf '%s' 'Unable to activate the xaac-admin password.' ;;\n"
                "        en:admin_altered) printf '%s' 'Final verification detected that xaac-admin was locked or altered again.' ;;\n"
                "        en:admin_hash_fail) printf '%s' 'The xaac-admin hash was not written to the target system.' ;;\n"
                "        en:admin_ok) printf '%s' 'Administrative password validated. Installation is starting.' ;;\n"
                "        en:admin_shell_fail) printf '%s' 'The xaac-admin shell is not interactive.' ;;\n"
                "        en:all_data) printf '%s' 'All data on this disk will be erased immediately after confirmation.' ;;\n"
                "        en:block5_missing) printf '%s' 'The Block 5 integration marker is missing.' ;;\n"
                "        en:capacity) printf '%s' 'Capacity' ;;\n"
                "        en:complete) printf '%s' 'Installation completed and verified. The disk is now bootable in UEFI mode.' ;;\n"
                "        en:configure_hostname) printf '%s' 'Configure the machine name.' ;;\n"
                "        en:configure_password) printf '%s' 'Configure the local xaac-admin password now.' ;;\n"
                "        en:configure_rdp) printf '%s' 'Configure the primary RDP server.' ;;\n"
                "        en:confirm) printf '%s' 'To confirm the selection, type exactly: INSTALL XAAC' ;;\n"
                "        en:confirmation_bad) printf '%s' 'Incorrect confirmation. No changes were made.' ;;\n"
                "        en:confirmation_ok) printf '%s' 'Confirmation accepted.' ;;\n"
                "        en:device) printf '%s' 'Device' ;;\n"
                "        en:dhcp) printf '%s' 'Ethernet will be configured automatically using DHCP.' ;;\n"
                "        en:dhcp_final_fail) printf '%s' 'DHCP networking was not configured.' ;;\n"
                "        en:disk_changed) printf '%s' 'The disk has changed since detection.' ;;\n"
                "        en:disk_missing) printf '%s' 'The selected disk no longer exists.' ;;\n"
                "        en:disk_mounted) printf '%s' 'The disk or one of its partitions is mounted. Installation rejected.' ;;\n"
                "        en:disk_small) printf '%s' 'The disk is too small to install XAAC Thin Client OS.' ;;\n"
                "        en:disks) printf '%s' 'Detected disks:' ;;\n"
                "        en:esp_invalid) printf '%s' 'The first partition is not a valid GPT ESP.' ;;\n"
                "        en:fallback_uuid) printf '%s' 'The GRUB fallback does not reference the root UUID.' ;;\n"
                "        en:fat_invalid) printf '%s' 'The EFI FAT32 partition failed verification.' ;;\n"
                "        en:grub_entry_fail) printf '%s' 'grub.cfg does not contain the XAAC Thin Client OS entry.' ;;\n"
                "        en:grub_initrd_fail) printf '%s' 'grub.cfg does not contain an initrd command.' ;;\n"
                "        en:grub_linux_fail) printf '%s' 'grub.cfg does not contain a linux command to load the kernel.' ;;\n"
                "        en:grub_signed_missing) printf '%s' 'Signed grubx64.efi was not found.' ;;\n"
                "        en:grubcfg_fail) printf '%s' 'Unable to generate grub.cfg.' ;;\n"
                "        en:hash_fail) printf '%s' 'Unable to generate the SHA-512 hash for xaac-admin.' ;;\n"
                "        en:hostname_final_fail) printf '%s' 'The hostname was not configured.' ;;\n"
                "        en:hostname_invalid) printf '%s' 'Invalid hostname.' ;;\n"
                "        en:hostname_long) printf '%s' 'Hostname too long.' ;;\n"
                "        en:hostname_prompt) printf '%s' 'Hostname [xaac-thin-client]: ' ;;\n"
                "        en:hosts_final_fail) printf '%s' '/etc/hosts does not contain the hostname.' ;;\n"
                "        en:identity_fail) printf '%s' 'The installed system identity is incorrect.' ;;\n"
                "        en:initrd_live_missing) printf '%s' 'The Live media initramfs was not found.' ;;\n"
                "        en:installer_remains) printf '%s' 'The installer program is still present on the installed system.' ;;\n"
                "        en:installer_service_remains) printf '%s' 'The installer service is still enabled.' ;;\n"
                "        en:internal) printf '%s' 'internal' ;;\n"
                "        en:invalid_option) printf '%s' 'Invalid option.' ;;\n"
                "        en:invalid_pe) printf '%s' 'Not a valid PE/COFF executable:' ;;\n"
                "        en:invalid_selection) printf '%s' 'Invalid selection.' ;;\n"
                "        en:invalid_target) printf '%s' 'Invalid target device.' ;;\n"
                "        en:kernel_copy_fail) printf '%s' 'The kernel or initramfs was not installed in /boot.' ;;\n"
                "        en:kernel_live_missing) printf '%s' 'The Live media kernel was not found.' ;;\n"
                "        en:kernel_unknown) printf '%s' 'Unable to determine the installed kernel version.' ;;\n"
                "        en:keyboard_es) printf '%s' 'Spanish' ;;\n"
                "        en:keyboard_final_fail) printf '%s' 'The selected keyboard layout was not applied.' ;;\n"
                "        en:keyboard_prompt) printf '%s' 'Select keyboard layout [1]: ' ;;\n"
                "        en:keyboard_title) printf '%s' 'Keyboard layout' ;;\n"
                "        en:keyboard_us) printf '%s' 'English (US)' ;;\n"
                "        en:kiosk_lock_fail) printf '%s' 'The xaac-kiosk account must remain locked.' ;;\n"
                "        en:kiosk_shell_fail) printf '%s' 'xaac-kiosk cannot have an interactive shell.' ;;\n"
                "        en:live_disk) printf '%s' 'The selected disk contains the active Live system. Installation rejected.' ;;\n"
                "        en:locale_final_fail) printf '%s' 'The selected locale was not applied.' ;;\n"
                "        en:marker_missing) printf '%s' 'The consolidation marker is missing.' ;;\n"
                "        en:missing_file) printf '%s' 'Missing or empty file:' ;;\n"
                "        en:model) printf '%s' 'Model' ;;\n"
                "        en:model_unknown) printf '%s' 'Model not reported' ;;\n"
                "        en:no_ac) printf '%s' 'External power was not detected. Installation rejected.' ;;\n"
                "        en:no_disk) printf '%s' 'No writable disk was detected.' ;;\n"
                "        en:out_range) printf '%s' 'Selection out of range.' ;;\n"
                "        en:package_missing) printf '%s' 'xaac-thinclient 1.0.0 is not installed.' ;;\n"
                "        en:pam_fail) printf '%s' 'PAM rejected the xaac-admin password.' ;;\n"
                "        en:partition_fail) printf '%s' 'Partition was not created:' ;;\n"
                "        en:password) printf '%s' 'Password: ' ;;\n"
                "        en:password_colon) printf '%s' 'The password cannot contain a colon (:).' ;;\n"
                "        en:password_mismatch) printf '%s' 'Passwords do not match.' ;;\n"
                "        en:password_rules) printf '%s' 'It must contain at least 12 characters and cannot contain a colon (:).' ;;\n"
                "        en:password_short) printf '%s' 'The password is too short.' ;;\n"
                "        en:poweroff) printf '%s' 'Press Enter to power off the system: ' ;;\n"
                "        en:preflight) printf '%s' 'Preflight checks, GPT partitioning, formatting and base system deployment.' ;;\n"
                "        en:rdp_domain) printf '%s' 'RDP domain: ' ;;\n"
                "        en:rdp_domain_empty) printf '%s' 'The RDP domain cannot be empty.' ;;\n"
                "        en:rdp_host) printf '%s' 'RDP server (DNS name or IP): ' ;;\n"
                "        en:rdp_host_empty) printf '%s' 'The RDP server cannot be empty.' ;;\n"
                "        en:rdp_host_invalid) printf '%s' 'Invalid RDP server.' ;;\n"
                "        en:reboot) printf '%s' 'Press Enter to reboot the system: ' ;;\n"
                "        en:removable) printf '%s' 'removable' ;;\n"
                "        en:removable_warning) printf '%s' 'Warning: the selected device is marked as removable.' ;;\n"
                "        en:repeat_password) printf '%s' 'Repeat password: ' ;;\n"
                "        en:root_lock_fail) printf '%s' 'The root account must remain locked.' ;;\n"
                "        en:rootfs_missing) printf '%s' 'filesystem.squashfs was not found on the Live media.' ;;\n"
                "        en:s1) printf '%s' '[1/10] Creating the GPT table and partitions...' ;;\n"
                "        en:s10) printf '%s' '[10/10] Verifying the installation...' ;;\n"
                "        en:s2) printf '%s' '[2/10] Creating filesystems...' ;;\n"
                "        en:s3) printf '%s' '[3/10] Mounting the target...' ;;\n"
                "        en:s4) printf '%s' '[4/10] Deploying the base system...' ;;\n"
                "        en:s5) printf '%s' '[5/10] Installing the kernel and initramfs on the target system...' ;;\n"
                "        en:s6) printf '%s' '[6/10] Generating mount configuration...' ;;\n"
                "        en:s7) printf '%s' '[7/10] Installing GRUB UEFI...' ;;\n"
                "        en:s8) printf '%s' '[8/10] Configuring the local administrator...' ;;\n"
                "        en:s9) printf '%s' '[9/10] Consolidating the installed system and preparing first boot...' ;;\n"
                "        en:select_disk) printf '%s' 'Select the disk number: ' ;;\n"
                "        en:shim_missing) printf '%s' 'Signed shimx64.efi was not found.' ;;\n"
                "        en:ssh_config_fail) printf '%s' 'The installed OpenSSH configuration is invalid.' ;;\n"
                "        en:ssh_key_fail) printf '%s' 'Unable to generate the OpenSSH ED25519 host key.' ;;\n"
                "        en:ssh_pub_fail) printf '%s' 'Unable to generate the OpenSSH public ED25519 host key.' ;;\n"
                "        en:summary) printf '%s' 'DESTRUCTIVE OPERATION SUMMARY' ;;\n"
                "        en:thinclient_missing) printf '%s' 'XAAC Thin Client is missing from the installed system.' ;;\n"
                "        en:title) printf '%s' 'XAAC Thin Client OS — Installer (step 5)' ;;\n"
                "        en:uuid_fail) printf '%s' 'Unable to obtain all UUIDs.' ;;\n"
                "        en:warning) printf '%s' 'WARNING: this step erases all data on the selected disk.' ;;\n"
                "        *) printf '%s' \"$key\" ;;\n"
                "    esac\n"
                "}\n"
                "xaac_say() { xaac_msg \"$1\"; printf '\\n'; }\n"
                "xaac_prompt() { xaac_msg \"$1\"; }\n"
                "disks_file=\n"
                "mount_root=\n"
                "cleanup_install() {\n"
                "    [ -n \"${mount_root:-}\" ] || return 0\n"
                "    sync || true\n"
                "    for mounted in \"$mount_root/run\" \"$mount_root/sys\" \"$mount_root/proc\" \"$mount_root/dev\" \"$mount_root/boot/efi\" \"$mount_root/data\" \"$mount_root/recovery\" \"$mount_root\"; do\n"
                "        if mountpoint -q \"$mounted\"; then\n"
                "            umount -R \"$mounted\" 2>/dev/null || umount -l \"$mounted\" 2>/dev/null || true\n"
                "        fi\n"
                "    done\n"
                "}\n"
                "xaac_installer_exit() {\n"
                "    status=$?\n"
                "    trap - EXIT HUP INT TERM\n"
                "    cleanup_install\n"
                "    [ -z \"${disks_file:-}\" ] || rm -f \"$disks_file\"\n"
                "    if [ \"$status\" -ne 0 ]; then\n"
                "        printf '\\n'\n"
                "        xaac_say failure\n"
                "        xaac_prompt failure_reboot\n"
                "        IFS= read -r _answer || true\n"
                "        systemctl reboot || true\n"
                "        while :; do sleep 3600; done\n"
                "    fi\n"
                "    return 0\n"
                "}\n"
                "xaac_request_reboot() {\n"
                "    trap - EXIT HUP INT TERM\n"
                "    systemctl reboot\n"
                "    while :; do sleep 3600; done\n"
                "}\n"
                "xaac_request_poweroff() {\n"
                "    trap - EXIT HUP INT TERM\n"
                "    systemctl poweroff\n"
                "    while :; do sleep 3600; done\n"
                "}\n"
                "trap 'xaac_installer_exit' EXIT\n"
                "trap 'exit 130' HUP INT TERM\n"
                "clear\n"
                "printf '%s\\n' 'XAAC Thin Client OS'\n"
                "printf '%s\\n' '==================='\n"
                "printf '\\n%s\\n' \"Seleccioneu l'idioma / Seleccione el idioma / Select language\"\n"
                "printf '%s\\n' '  1) Valencià / Català'\n"
                "printf '%s\\n' '  2) Español'\n"
                "printf '%s\\n' '  3) English'\n"
                "while :; do\n"
                "    printf '%s' 'Seleccioneu / Seleccione / Select [1]: '\n"
                "    IFS= read -r language_choice\n"
                "    [ -n \"$language_choice\" ] || language_choice=1\n"
                "    case $language_choice in\n"
                "        1) install_language=ca; install_locale=ca_ES.UTF-8; install_language_env=ca_ES:ca; break ;;\n"
                "        2) install_language=es; install_locale=es_ES.UTF-8; install_language_env=es_ES:es; break ;;\n"
                "        3) install_language=en; install_locale=en_US.UTF-8; install_language_env=en_US:en; break ;;\n"
                "        *) printf '%s\\n' 'Opció no vàlida / Opción no válida / Invalid option.' ;;\n"
                "    esac\n"
                "done\n"
                "export LANG=$install_locale\n"
                "export LC_ALL=$install_locale\n"
                "printf '\\n'\n"
                "xaac_say keyboard_title\n"
                "printf '%s\\n' \"  1) $(xaac_msg keyboard_es)\"\n"
                "printf '%s\\n' \"  2) $(xaac_msg keyboard_us)\"\n"
                "while :; do\n"
                "    xaac_prompt keyboard_prompt\n"
                "    IFS= read -r keyboard_choice\n"
                "    [ -n \"$keyboard_choice\" ] || keyboard_choice=1\n"
                "    case $keyboard_choice in\n"
                "        1) install_keyboard_layout=es; install_keymap=es; break ;;\n"
                "        2) install_keyboard_layout=us; install_keymap=us; break ;;\n"
                "        *) xaac_say invalid_option ;;\n"
                "    esac\n"
                "done\n"
                "if command -v loadkeys >/dev/null 2>&1; then loadkeys \"$install_keymap\" >/dev/null 2>&1 || true; fi\n"
                "clear\n"
                "xaac_say title\n"
                "printf '%s\\n' '============================================'\n"
                "printf '\\n'\n"
                "xaac_say preflight\n"
                "xaac_say warning\n"
                "printf '\\n'\n"
                "disks_file=$(mktemp)\n"
                "lsblk -bdnP -o NAME,SIZE,MODEL,TYPE,RO,RM | while IFS= read -r line; do\n"
                "    eval \"$line\"\n"
                "    [ \"${TYPE:-}\" = disk ] || continue\n"
                "    [ \"${RO:-1}\" = 0 ] || continue\n"
                "    base=${NAME##*/}\n"
                "    case $base in loop*|ram*|zram*|sr*) continue ;; esac\n"
                "    printf '%s\\t%s\\t%s\\t%s\\n' \"$NAME\" \"$SIZE\" \"${MODEL:-}\" \"${RM:-0}\"\n"
                "done > \"$disks_file\"\n"
                "if [ ! -s \"$disks_file\" ]; then\n"
                "    xaac_say no_disk\n"
                "    xaac_prompt reboot\n"
                "    IFS= read -r _answer\n"
                "    xaac_request_reboot\n"
                "fi\n"
                "xaac_say disks\n"
                "printf '\\n'\n"
                "i=1\n"
                "while IFS='\\t' read -r name size_bytes model removable; do\n"
                "    [ -n \"$model\" ] || model=$(xaac_msg model_unknown)\n"
                "    size_human=$(numfmt --to=iec-i --suffix=B \"$size_bytes\" 2>/dev/null || printf '%s bytes' \"$size_bytes\")\n"
                "    kind=$(xaac_msg internal)\n"
                "    [ \"$removable\" = 0 ] || kind=$(xaac_msg removable)\n"
                "    printf '  %s) %-14s %-9s %-10s %s\\n' \"$i\" \"$name\" \"$size_human\" \"$kind\" \"$model\"\n"
                "    i=$((i + 1))\n"
                "done < \"$disks_file\"\n"
                "printf '\\n'\n"
                "count=$(wc -l < \"$disks_file\" | tr -d ' ')\n"
                "while :; do\n"
                "    xaac_prompt select_disk\n"
                "    IFS= read -r choice\n"
                "    case $choice in\n"
                "        ''|*[!0-9]*) xaac_say invalid_selection ; continue ;;\n"
                "    esac\n"
                "    if [ \"$choice\" -ge 1 ] 2>/dev/null && [ \"$choice\" -le \"$count\" ]; then\n"
                "        break\n"
                "    fi\n"
                "    xaac_say out_range\n"
                "done\n"
                "selected=$(sed -n \"${choice}p\" \"$disks_file\")\n"
                "selected_name=$(printf '%s\\n' \"$selected\" | cut -f1)\n"
                "selected_size=$(printf '%s\\n' \"$selected\" | cut -f2)\n"
                "selected_model=$(printf '%s\\n' \"$selected\" | cut -f3)\n"
                "selected_rm=$(printf '%s\\n' \"$selected\" | cut -f4)\n"
                "target=/dev/$selected_name\n"
                "case $target in /dev/*) ;; *) xaac_say invalid_target; exit 1 ;; esac\n"
                "[ -b \"$target\" ] || { xaac_say disk_missing; exit 1; }\n"
                "current_size=$(lsblk -bdno SIZE \"$target\" | tr -d ' ')\n"
                "[ \"$current_size\" = \"$selected_size\" ] || { xaac_say disk_changed; exit 1; }\n"
                "minimum_size=7000000000\n"
                "if [ \"$selected_size\" -lt \"$minimum_size\" ]; then\n"
                "    xaac_say disk_small\n"
                "    exit 1\n"
                "fi\n"
                "if lsblk -nrpo MOUNTPOINT \"$target\" | grep -q '[^[:space:]]'; then\n"
                "    xaac_say disk_mounted\n"
                "    exit 1\n"
                "fi\n"
                "if [ \"$selected_rm\" != 0 ]; then\n"
                "    xaac_say removable_warning\n"
                "fi\n"
                "size_human=$(numfmt --to=iec-i --suffix=B \"$selected_size\" 2>/dev/null || printf '%s bytes' \"$selected_size\")\n"
                "printf '\\n'\n"
                "xaac_say summary\n"
                "printf '  %s: %s\\n' \"$(xaac_msg device)\" \"$target\"\n"
                "printf '  %s: %s\\n' \"$(xaac_msg capacity)\" \"$size_human\"\n"
                "printf '  %s: %s\\n' \"$(xaac_msg model)\" \"${selected_model:-$(xaac_msg model_unknown)}\"\n"
                "printf '\\n'\n"
                "xaac_say all_data\n"
                "xaac_say confirm\n"
                "printf '%s' '> '\n"
                "IFS= read -r confirmation\n"
                "if [ \"$confirmation\" != 'INSTALL XAAC' ]; then\n"
                "    xaac_say confirmation_bad\n"
                "    xaac_prompt reboot\n"
                "    IFS= read -r _answer\n"
                "    xaac_request_reboot\n"
                "fi\n"
                "printf '\\n'\n"
                "xaac_say confirmation_ok\n"
                "printf '\\n'; xaac_say configure_password\n"
                "xaac_say password_rules\n"
                "trap 'stty echo 2>/dev/null || true; exit 130' HUP INT TERM\n"
                "while :; do\n"
                "    xaac_prompt password\n"
                "    stty -echo\n"
                "    IFS= read -r admin_password || { stty echo; printf '\\n'; exit 1; }\n"
                "    stty echo\n"
                "    printf '\\n'; xaac_prompt repeat_password\n"
                "    stty -echo\n"
                "    IFS= read -r admin_password_confirm || { stty echo; printf '\\n'; exit 1; }\n"
                "    stty echo\n"
                "    printf '\\n'\n"
                "    [ \"$admin_password\" = \"$admin_password_confirm\" ] || { xaac_say password_mismatch; continue; }\n"
                "    [ \"${#admin_password}\" -ge 12 ] || { xaac_say password_short; continue; }\n"
                "    case $admin_password in *:*) xaac_say password_colon; continue ;; esac\n"
                "    break\n"
                "done\n"
                "trap 'exit 130' HUP INT TERM\n"
                "unset admin_password_confirm\n"
                "printf '\n"
                "'; xaac_say configure_hostname\n"
                "while :; do\n"
                "    xaac_prompt hostname_prompt\n"
                "    IFS= read -r install_hostname\n"
                "    [ -n \"$install_hostname\" ] || install_hostname=xaac-thin-client\n"
                "    case $install_hostname in *[!A-Za-z0-9-]*|-*|*-) xaac_say hostname_invalid; continue ;; esac\n"
                "    [ \"${#install_hostname}\" -le 63 ] || { xaac_say hostname_long; continue; }\n"
                "    break\n"
                "done\n"
                "printf '\n"
                "'; xaac_say configure_rdp\n"
                "while :; do\n"
                "    xaac_prompt rdp_host\n"
                "    IFS= read -r install_rdp_host\n"
                "    [ -n \"$install_rdp_host\" ] || { xaac_say rdp_host_empty; continue; }\n"
                "    case $install_rdp_host in *[!A-Za-z0-9.:-]*) xaac_say rdp_host_invalid; continue ;; esac\n"
                "    break\n"
                "done\n"
                "while :; do\n"
                "    xaac_prompt rdp_domain\n"
                "    IFS= read -r install_rdp_domain\n"
                "    [ -n \"$install_rdp_domain\" ] || { xaac_say rdp_domain_empty; continue; }\n"
                "    break\n"
                "done\n"
                "xaac_say dhcp\n"
                "xaac_say admin_ok\n"
                "live_source=$(findmnt -nro SOURCE /run/live/medium 2>/dev/null || true)\n"
                "if [ -n \"$live_source\" ]; then\n"
                "    live_parent=$(lsblk -ndo PKNAME \"$live_source\" 2>/dev/null | head -n1)\n"
                "    [ -n \"$live_parent\" ] || live_parent=${live_source#/dev/}\n"
                "    [ \"$target\" != \"/dev/$live_parent\" ] || { xaac_say live_disk; exit 1; }\n"
                "fi\n"
                "ac_found=0; ac_online=0\n"
                "for supply in /sys/class/power_supply/*; do\n"
                "    [ -e \"$supply/type\" ] || continue\n"
                "    case $(cat \"$supply/type\" 2>/dev/null || true) in Mains|USB|USB_C) ac_found=1 ;; *) continue ;; esac\n"
                "    [ \"$(cat \"$supply/online\" 2>/dev/null || printf 0)\" = 1 ] && ac_online=1\n"
                "done\n"
                "if [ \"$ac_found\" = 1 ] && [ \"$ac_online\" != 1 ]; then xaac_say no_ac; exit 1; fi\n"
                "case $target in *[0-9]) p1=${target}p1; p2=${target}p2; p3=${target}p3; p4=${target}p4 ;; *) p1=${target}1; p2=${target}2; p3=${target}3; p4=${target}4 ;; esac\n"
                "mount_root=/mnt/xaac-target\n"
                "xaac_say s1\n"
                "wipefs --all --force \"$target\"\n"
                "sgdisk --zap-all \"$target\"\n"
                "sgdisk -n 1:0:+256M -t 1:ef00 -c 1:XAAC_EFI \"$target\"\n"
                "sgdisk -n 2:0:+4096M -t 2:8300 -c 2:XAAC_ROOT \"$target\"\n"
                "sgdisk -n 3:0:+1024M -t 3:8300 -c 3:XAAC_DATA \"$target\"\n"
                "sgdisk -n 4:0:0 -t 4:8300 -c 4:XAAC_RECOVERY \"$target\"\n"
                "partprobe \"$target\"; udevadm settle\n"
                "for partition in \"$p1\" \"$p2\" \"$p3\" \"$p4\"; do [ -b \"$partition\" ] || { printf '%s %s\\n' \"$(xaac_msg partition_fail)\" \"$partition\"; exit 1; }; done\n"
                "xaac_say s2\n"
                "mkfs.vfat -F 32 -n XAAC_EFI \"$p1\"\n"
                "mkfs.ext4 -F -L XAAC_ROOT \"$p2\"\n"
                "mkfs.ext4 -F -L XAAC_DATA \"$p3\"\n"
                "mkfs.ext4 -F -L XAAC_RECOVERY \"$p4\"\n"
                "xaac_say s3\n"
                "mkdir -p \"$mount_root\"; mount \"$p2\" \"$mount_root\"\n"
                "mkdir -p \"$mount_root/boot/efi\" \"$mount_root/data\" \"$mount_root/recovery\"\n"
                "mount \"$p1\" \"$mount_root/boot/efi\"; mount \"$p3\" \"$mount_root/data\"; mount \"$p4\" \"$mount_root/recovery\"\n"
                "xaac_say s4\n"
                "rootfs_image=/run/live/medium/live/filesystem.squashfs\n"
                "[ -r \"$rootfs_image\" ] || { xaac_say rootfs_missing; exit 1; }\n"
                "unsquashfs -f -d \"$mount_root\" \"$rootfs_image\"\n"
                "xaac_say s5\n"
                "kernel_version=$(find \"$mount_root/lib/modules\" -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' | sort -V | tail -n1)\n"
                "[ -n \"$kernel_version\" ] || { xaac_say kernel_unknown; exit 1; }\n"
                "[ -r /run/live/medium/live/vmlinuz ] || { xaac_say kernel_live_missing; exit 1; }\n"
                "[ -r /run/live/medium/live/initrd.img ] || { xaac_say initrd_live_missing; exit 1; }\n"
                "mkdir -p \"$mount_root/boot\"\n"
                "install -m 0644 /run/live/medium/live/vmlinuz \"$mount_root/boot/vmlinuz-$kernel_version\"\n"
                "install -m 0644 /run/live/medium/live/initrd.img \"$mount_root/boot/initrd.img-$kernel_version\"\n"
                "ln -sfn \"vmlinuz-$kernel_version\" \"$mount_root/boot/vmlinuz\"\n"
                "ln -sfn \"initrd.img-$kernel_version\" \"$mount_root/boot/initrd.img\"\n"
                "[ -s \"$mount_root/boot/vmlinuz-$kernel_version\" ] && [ -s \"$mount_root/boot/initrd.img-$kernel_version\" ] || { xaac_say kernel_copy_fail; exit 1; }\n"
                "xaac_say s6\n"
                "root_uuid=$(blkid -s UUID -o value \"$p2\"); efi_uuid=$(blkid -s UUID -o value \"$p1\"); data_uuid=$(blkid -s UUID -o value \"$p3\"); recovery_uuid=$(blkid -s UUID -o value \"$p4\")\n"
                "[ -n \"$root_uuid\" ] && [ -n \"$efi_uuid\" ] && [ -n \"$data_uuid\" ] && [ -n \"$recovery_uuid\" ] || { xaac_say uuid_fail; exit 1; }\n"
                "cat > \"$mount_root/etc/fstab\" <<EOF\n"
                "UUID=$root_uuid / ext4 defaults,noatime 0 1\n"
                "UUID=$efi_uuid /boot/efi vfat umask=0077 0 1\n"
                "UUID=$data_uuid /data ext4 defaults,noatime 0 2\n"
                "UUID=$recovery_uuid /recovery ext4 defaults,noatime 0 2\n"
                "EOF\n"
                "xaac_say s7\n"
                "mkdir -p \"$mount_root/dev\" \"$mount_root/proc\" \"$mount_root/sys\" \"$mount_root/run\"\n"
                "mount --rbind /dev \"$mount_root/dev\"; mount --make-rslave \"$mount_root/dev\"\n"
                "mount -t proc proc \"$mount_root/proc\"\n"
                "mount --rbind /sys \"$mount_root/sys\"; mount --make-rslave \"$mount_root/sys\"\n"
                "mount --rbind /run \"$mount_root/run\"; mount --make-rslave \"$mount_root/run\"\n"
                "mkdir -p \"$mount_root/etc/default/grub.d\" \"$mount_root/etc/grub.d\"\n"
                "cat > \"$mount_root/etc/default/grub.d/10-xaac-identity.cfg\" <<'EOF'\n"
                "GRUB_DISTRIBUTOR=\"XAAC Thin Client OS\"\n"
                "GRUB_DISABLE_SUBMENU=y\n"
                "GRUB_TIMEOUT=0\n"
                "GRUB_TIMEOUT_STYLE=hidden\n"
                "GRUB_RECORDFAIL_TIMEOUT=0\n"
                "GRUB_DISABLE_RECOVERY=true\n"
                "GRUB_DISABLE_OS_PROBER=true\n"
                "GRUB_GFXPAYLOAD_LINUX=keep\n"
                "EOF\n"
                "cat > \"$mount_root/etc/grub.d/09_xaac\" <<EOF\n"
                "#!/bin/sh\n"
                "cat <<'XAAC_ENTRY'\n"
                "menuentry 'XAAC Thin Client OS' --class xaac --class gnu-linux --class gnu --class os {\n"
                "    insmod part_gpt\n"
                "    insmod ext2\n"
                "    search --no-floppy --fs-uuid --set=root $root_uuid\n"
                "    linux /boot/vmlinuz root=UUID=$root_uuid ro __XAAC_KERNEL_CMDLINE__\n"
                "    initrd /boot/initrd.img\n"
                "}\n"
                "XAAC_ENTRY\n"
                "EOF\n"
                "chmod 0755 \"$mount_root/etc/grub.d/09_xaac\"\n"
                "chmod -x \"$mount_root/etc/grub.d/10_linux\"\n"
                "chroot \"$mount_root\" grub-install --target=x86_64-efi --efi-directory=/boot/efi --boot-directory=/boot --bootloader-id=XAAC --removable --no-nvram --recheck\n"
                "chroot \"$mount_root\" update-grub\n"
                "signed_shim=\"$mount_root/usr/lib/shim/shimx64.efi.signed\"\n"
                "signed_grub=\"$mount_root/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed\"\n"
                "signed_mok=\"$mount_root/usr/lib/shim/mmx64.efi.signed\"\n"
                "[ -s \"$signed_shim\" ] || { xaac_say shim_missing; exit 1; }\n"
                "[ -s \"$signed_grub\" ] || { xaac_say grub_signed_missing; exit 1; }\n"
                "mkdir -p \"$mount_root/boot/efi/EFI/BOOT\" \"$mount_root/boot/efi/EFI/XAAC\"\n"
                "install -m 0644 \"$signed_shim\" \"$mount_root/boot/efi/EFI/BOOT/BOOTX64.EFI\"\n"
                "install -m 0644 \"$signed_grub\" \"$mount_root/boot/efi/EFI/BOOT/grubx64.efi\"\n"
                "install -m 0644 \"$signed_shim\" \"$mount_root/boot/efi/EFI/XAAC/shimx64.efi\"\n"
                "install -m 0644 \"$signed_grub\" \"$mount_root/boot/efi/EFI/XAAC/grubx64.efi\"\n"
                "if [ -s \"$signed_mok\" ]; then install -m 0644 \"$signed_mok\" \"$mount_root/boot/efi/EFI/BOOT/mmx64.efi\"; install -m 0644 \"$signed_mok\" \"$mount_root/boot/efi/EFI/XAAC/mmx64.efi\"; fi\n"
                "cat > \"$mount_root/boot/efi/EFI/BOOT/grub.cfg\" <<EOF\n"
                "search --no-floppy --fs-uuid --set=root $root_uuid\n"
                "set prefix=(\\$root)/boot/grub\n"
                "configfile \\$prefix/grub.cfg\n"
                "EOF\n"
                "cp \"$mount_root/boot/efi/EFI/BOOT/grub.cfg\" \"$mount_root/boot/efi/EFI/XAAC/grub.cfg\"\n"
                "[ -s \"$mount_root/boot/grub/grub.cfg\" ] || { xaac_say grubcfg_fail; exit 1; }\n"
                "grep -Fq \"menuentry 'XAAC Thin Client OS'\" \"$mount_root/boot/grub/grub.cfg\" || { xaac_say grub_entry_fail; exit 1; }\n"
                "grep -Eq \"^[[:space:]]*linux[[:space:]]+.*vmlinuz\" \"$mount_root/boot/grub/grub.cfg\" || { xaac_say grub_linux_fail; exit 1; }\n"
                "grep -Eq \"^[[:space:]]*initrd[[:space:]]+.*initrd\" \"$mount_root/boot/grub/grub.cfg\" || { xaac_say grub_initrd_fail; exit 1; }\n"
                "for efi_file in \"$mount_root/boot/efi/EFI/BOOT/BOOTX64.EFI\" \"$mount_root/boot/efi/EFI/BOOT/grubx64.efi\"; do [ -s \"$efi_file\" ] || { printf '%s %s\\n' \"$(xaac_msg missing_file)\" \"$efi_file\"; exit 1; }; [ \"$(od -An -tx1 -N2 \"$efi_file\" | tr -d ' \\n')\" = 4d5a ] || { printf '%s %s\\n' \"$(xaac_msg invalid_pe)\" \"$efi_file\"; exit 1; }; done\n"
                "grep -Fq \"$root_uuid\" \"$mount_root/boot/efi/EFI/BOOT/grub.cfg\" || { xaac_say fallback_uuid; exit 1; }\n"
                "sgdisk -i 1 \"$target\" | grep -Eqi 'EF00|EFI system partition' || { xaac_say esp_invalid; exit 1; }\n"
                "sync; umount \"$mount_root/boot/efi\"\n"
                "fsck.vfat -n \"$p1\" >/dev/null || { xaac_say fat_invalid; exit 1; }\n"
                "mount \"$p1\" \"$mount_root/boot/efi\"\n"
                "xaac_say s8\n"
                "admin_hash=$(printf '%s' \"$admin_password\" | openssl passwd -6 -stdin)\n"
                "case \"$admin_hash\" in '$6$'*) ;; *) xaac_say hash_fail; exit 1 ;; esac\n"
                "printf 'xaac-admin:%s\\n' \"$admin_hash\" | chroot \"$mount_root\" chpasswd --encrypted\n"
                "chroot \"$mount_root\" usermod --unlock --shell /bin/bash xaac-admin\n"
                "chroot \"$mount_root\" chage -E -1 -I -1 -m 0 xaac-admin\n"
                "passwd_status=$(chroot \"$mount_root\" passwd -S xaac-admin 2>/dev/null | awk '{print $2}')\n"
                "shadow_password=$(awk -F: '$1 == \"xaac-admin\" {print $2}' \"$mount_root/etc/shadow\")\n"
                "admin_shell=$(chroot \"$mount_root\" getent passwd xaac-admin 2>/dev/null | cut -d: -f7)\n"
                "[ \"$passwd_status\" = P ] || { xaac_say admin_activate_fail; exit 1; }\n"
                "[ \"$shadow_password\" = \"$admin_hash\" ] || { xaac_say admin_hash_fail; exit 1; }\n"
                "[ \"$admin_shell\" = /bin/bash ] || { xaac_say admin_shell_fail; exit 1; }\n"
                "root_status=$(chroot \"$mount_root\" passwd -S root 2>/dev/null | awk '{print $2}')\n"
                "kiosk_status=$(chroot \"$mount_root\" passwd -S xaac-kiosk 2>/dev/null | awk '{print $2}')\n"
                "kiosk_shell=$(chroot \"$mount_root\" getent passwd xaac-kiosk 2>/dev/null | cut -d: -f7)\n"
                "[ \"$root_status\" = L ] || { xaac_say root_lock_fail; exit 1; }\n"
                "[ \"$kiosk_status\" = L ] || { xaac_say kiosk_lock_fail; exit 1; }\n"
                "[ \"$kiosk_shell\" = /usr/sbin/nologin ] || { xaac_say kiosk_shell_fail; exit 1; }\n"
                "printf '%s\\n' \"$admin_password\" | chroot \"$mount_root\" pamtester login xaac-admin authenticate >/dev/null 2>&1 || { xaac_say pam_fail; exit 1; }\n"
                "chroot \"$mount_root\" mkdir -p /var/lib/xaac/admin\n"
                "chroot \"$mount_root\" install -o root -g xaac-admin -m 0640 /dev/null /var/lib/xaac/admin/password-changed\n"
                "xaac_say s9\n"
                "printf '%s\\n' \"$install_hostname\" > \"$mount_root/etc/hostname\"\n"
                "printf '127.0.0.1 localhost\\n127.0.1.1 %s\\n::1 localhost ip6-localhost ip6-loopback\\n' \"$install_hostname\" > \"$mount_root/etc/hosts\"\n"
                "printf 'LANG=%s\\nLANGUAGE=%s\\n' \"$install_locale\" \"$install_language_env\" > \"$mount_root/etc/locale.conf\"\n"
                "printf 'LANG=%s\\nLANGUAGE=%s\\n' \"$install_locale\" \"$install_language_env\" > \"$mount_root/etc/default/locale\"\n"
                "printf 'XKBMODEL=\"pc105\"\\nXKBLAYOUT=\"%s\"\\nXKBVARIANT=\"\"\\nXKBOPTIONS=\"\"\\nBACKSPACE=\"guess\"\\n' \"$install_keyboard_layout\" > \"$mount_root/etc/default/keyboard\"\n"
                "if [ -f \"$mount_root/etc/xaac-thinclient/device.ini\" ]; then sed -i \"s/^device_name[[:space:]]*=.*/device_name = $install_hostname/\" \"$mount_root/etc/xaac-thinclient/device.ini\"; fi\n"
                "if [ -f \"$mount_root/etc/xaac-thinclient/servers.ini\" ]; then sed -i \"s/^host[[:space:]]*=.*/host = $install_rdp_host/; s/^domain[[:space:]]*=.*/domain = $install_rdp_domain/; s/^enabled[[:space:]]*=.*/enabled = true/\" \"$mount_root/etc/xaac-thinclient/servers.ini\"; fi\n"
                "mkdir -p \"$mount_root/etc/NetworkManager/system-connections\"\n"
                "cat > \"$mount_root/etc/NetworkManager/system-connections/xaac-wired.nmconnection\" <<EOF\n"
                "[connection]\n"
                "id=XAAC Wired DHCP\n"
                "type=ethernet\n"
                "autoconnect=true\n"
                "match-device=type:ethernet\n"
                "\n"
                "[ipv4]\n"
                "method=auto\n"
                "\n"
                "[ipv6]\n"
                "method=auto\n"
                "EOF\n"
                "chmod 0600 \"$mount_root/etc/NetworkManager/system-connections/xaac-wired.nmconnection\"\n"
                "chroot \"$mount_root\" systemctl enable NetworkManager.service >/dev/null\n"
                "mkdir -p \"$mount_root/etc/xaac\" \"$mount_root/var/lib/xaac/installation\" \"$mount_root/recovery/installer\"\n"
                "cp \"$mount_root/etc/os-release\" \"$mount_root/etc/xaac/os-release\"\n"
                "rm -f \"$mount_root/etc/systemd/system/multi-user.target.wants/xaac-installer-welcome.service\"\n"
                "rm -f \"$mount_root/etc/systemd/system/xaac-installer-welcome.service\" \"$mount_root/usr/local/sbin/xaac-installer-welcome\"\n"
                "rm -rf \"$mount_root/etc/systemd/system/getty@tty1.service.d\"\n"
                "rm -f \"$mount_root/etc/systemd/system/getty.target.wants/getty@tty1.service\"\n"
                "ln -sfn /dev/null \"$mount_root/etc/systemd/system/getty@tty1.service\"\n"
                "chroot \"$mount_root\" usermod --shell /usr/sbin/nologin xaac-kiosk\n"
                "chroot \"$mount_root\" systemctl enable greetd.service >/dev/null\n"
                "chroot \"$mount_root\" systemctl set-default graphical.target >/dev/null\n"
                "rm -f \"$mount_root/run/xaac-installer\"* \"$mount_root/tmp/xaac-installer\"* 2>/dev/null || true\n"
                "printf \"status=consolidated\\ninstaller_removed=yes\\nidentity=xaac-thin-client-os\\n\" > \"$mount_root/var/lib/xaac/installation/consolidated\"\n"
                ": > \"$mount_root/etc/machine-id\"\n"
                "rm -f \"$mount_root/var/lib/dbus/machine-id\" \"$mount_root\"/etc/ssh/ssh_host_* \"$mount_root/var/lib/systemd/random-seed\"\n"
                "chroot \"$mount_root\" ssh-keygen -A\n"
                "test -s \"$mount_root/etc/ssh/ssh_host_ed25519_key\" || { xaac_say ssh_key_fail; exit 1; }\n"
                "test -s \"$mount_root/etc/ssh/ssh_host_ed25519_key.pub\" || { xaac_say ssh_pub_fail; exit 1; }\n"
                "chroot \"$mount_root\" /usr/sbin/sshd -t || { xaac_say ssh_config_fail; exit 1; }\n"
                "chroot \"$mount_root\" systemctl disable ssh.service >/dev/null 2>&1 || true\n"
                "touch \"$mount_root/var/lib/xaac/first-boot.pending\" \"$mount_root/etc/xaac-first-boot.pending\"\n"
                "xaac_say s10\n"
                "test -x \"$mount_root/usr/bin/systemctl\"\n"
                "test -f \"$mount_root/etc/fstab\"\n"
                "test -f \"$mount_root/boot/efi/EFI/BOOT/BOOTX64.EFI\"\n"
                "test -s \"$mount_root/boot/grub/grub.cfg\"\n"
                "test -x \"$mount_root/usr/bin/xaac-thinclient\" || { xaac_say thinclient_missing; exit 1; }\n"
                "test -f \"$mount_root/etc/xaac/block5-integration\" || { xaac_say block5_missing; exit 1; }\n"
                "chroot \"$mount_root\" dpkg-query -W -f='${Status} ${Version}\\n' xaac-thinclient | grep -Fq 'install ok installed 1.0.0' || { xaac_say package_missing; exit 1; }\n"
                "grep -Fq \"PRETTY_NAME=\\\"XAAC Thin Client OS\" \"$mount_root/etc/os-release\" || { xaac_say identity_fail; exit 1; }\n"
                "test ! -e \"$mount_root/usr/local/sbin/xaac-installer-welcome\" || { xaac_say installer_remains; exit 1; }\n"
                "test ! -e \"$mount_root/etc/systemd/system/multi-user.target.wants/xaac-installer-welcome.service\" || { xaac_say installer_service_remains; exit 1; }\n"
                "test -f \"$mount_root/var/lib/xaac/installation/consolidated\" || { xaac_say marker_missing; exit 1; }\n"
                "[ \"$(cat \"$mount_root/etc/hostname\")\" = \"$install_hostname\" ] || { xaac_say hostname_final_fail; exit 1; }\n"
                "grep -Fq \"127.0.1.1 $install_hostname\" \"$mount_root/etc/hosts\" || { xaac_say hosts_final_fail; exit 1; }\n"
                "grep -Fq \"method=auto\" \"$mount_root/etc/NetworkManager/system-connections/xaac-wired.nmconnection\" || { xaac_say dhcp_final_fail; exit 1; }\n"
                "grep -Fqx \"LANG=$install_locale\" \"$mount_root/etc/locale.conf\" || { xaac_say locale_final_fail; exit 1; }\n"
                "grep -Fqx \"LANG=$install_locale\" \"$mount_root/etc/default/locale\" || { xaac_say locale_final_fail; exit 1; }\n"
                "grep -Fqx \"XKBLAYOUT=\\\"$install_keyboard_layout\\\"\" \"$mount_root/etc/default/keyboard\" || { xaac_say keyboard_final_fail; exit 1; }\n"
                "final_shadow_password=$(awk -F: '$1 == \"xaac-admin\" {print $2}' \"$mount_root/etc/shadow\")\n"
                "[ \"$final_shadow_password\" = \"$admin_hash\" ] || { xaac_say admin_altered; exit 1; }\n"
                "admin_hash_fingerprint=$(printf '%s' \"$admin_hash\" | sha256sum | awk '{print $1}')\n"
                "printf 'status=configured\\nscheme=sha512\\nfingerprint=%s\\n' \"$admin_hash_fingerprint\" > \"$mount_root/var/lib/xaac/admin/install-credential-state\"\n"
                "chmod 0640 \"$mount_root/var/lib/xaac/admin/install-credential-state\"\n"
                "chown root:xaac-admin \"$mount_root/var/lib/xaac/admin/install-credential-state\"\n"
                "unset admin_password admin_hash final_shadow_password shadow_password\n"
                "cat > \"$mount_root/recovery/installer/installation-summary.txt\" <<EOF\n"
                "status=completed\n"
                "target=$target\n"
                "root_uuid=$root_uuid\n"
                "efi_uuid=$efi_uuid\n"
                "data_uuid=$data_uuid\n"
                "recovery_uuid=$recovery_uuid\n"
                "bootloader=shim-signed-grub-efi-amd64-removable\n"
                "locale=$install_locale\n"
                "keyboard_layout=$install_keyboard_layout\n"
                "EOF\n"
                "sync\n"
                "printf '\\n'\n"
                "xaac_say complete\n"
                "xaac_prompt poweroff\n"
                "IFS= read -r _answer\n"
                "xaac_request_poweroff\n"
            ).replace("__XAAC_KERNEL_CMDLINE__", installed_kernel_cmdline),
            0o755,
        )
        self._atomic_write(
            self._inside("/etc/systemd/system/xaac-installer-welcome.service"),
            "[Unit]\n"
            "Description=XAAC Thin Client OS complete installer (step 5)\n"
            "ConditionKernelCommandLine=xaac.mode=installer\n"
            "After=systemd-user-sessions.service\n"
            "Before=getty@tty1.service\n"
            "Conflicts=getty@tty1.service\n"
            "\n"
            "[Service]\n"
            "Type=idle\n"
            "PrivateMounts=yes\n"
            "ExecStartPre=-/bin/systemctl stop getty@tty1.service\n"
            "ExecStart=/usr/local/sbin/xaac-installer-welcome\n"
            "StandardInput=tty\n"
            "StandardOutput=tty\n"
            "StandardError=tty\n"
            "TTYPath=/dev/tty1\n"
            "TTYReset=yes\n"
            "TTYVHangup=yes\n"
            "TTYVTDisallocate=yes\n"
            "Restart=no\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n",
        )


        # Keep XAAC Thin Client language synchronisation outside the Live
        # Installer. The installed system applies it before greetd.
        self._atomic_write(
            self._inside("/usr/local/sbin/xaac-sync-thinclient-language"),
            "#!/bin/sh\n"
            "set -eu\n"
            "locale_file=/etc/locale.conf\n"
            "[ -r \"$locale_file\" ] || locale_file=/etc/default/locale\n"
            "config=/etc/xaac-thinclient/config.ini\n"
            "[ -r \"$locale_file\" ] || exit 0\n"
            "[ -f \"$config\" ] || exit 0\n"
            "locale_value=$(sed -n 's/^[[:space:]]*LANG[[:space:]]*=[[:space:]]*//p' \"$locale_file\" | head -n1 | tr -d '\"')\n"
            "case $locale_value in\n"
            "    ca|ca_*|ca.*) app_language=ca ;;\n"
            "    es|es_*|es.*) app_language=es ;;\n"
            "    en|en_*|en.*) app_language=en ;;\n"
            "    *) exit 0 ;;\n"
            "esac\n"
            "sed -i \"s/^[[:space:]]*language[[:space:]]*=.*/language = $app_language/\" \"$config\"\n"
            "grep -Eq \"^[[:space:]]*language[[:space:]]*=[[:space:]]*$app_language[[:space:]]*$\" \"$config\"\n",
            0o755,
        )
        self._atomic_write(
            self._inside("/etc/systemd/system/xaac-thinclient-language-sync.service"),
            "[Unit]\n"
            "Description=Synchronise XAAC Thin Client language with OS locale\n"
            "After=local-fs.target\n"
            "Before=greetd.service\n"
            "ConditionKernelCommandLine=!xaac.mode=installer\n"
            "ConditionPathExists=/etc/xaac-thinclient/config.ini\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/usr/local/sbin/xaac-sync-thinclient-language\n"
            "User=root\n"
            "Group=root\n"
            "UMask=0022\n\n"
            "[Install]\n"
            "WantedBy=graphical.target\n",
        )

        agent_debian_version = self._validate_xaac_agent_artifact()
        debs = self._copy_valid_debs()
        with self._chroot_mounts():
            self._install_runtime_packages()
            # Package-owned conffiles must exist before XAAC replaces them.
            # This ordering prevents greetd (and similar packages) from
            # blocking dpkg with an interactive conffile prompt.
            self._apply_kiosk_stack()
            self._configure_boot_splash()
            self._chroot(["locale-gen"], phase="configure-locales")
            self._chroot(["update-locale", f"LANG={self.settings.locale}"], phase="configure-update-locale")
            self._chroot(
                ["/bin/sh", "-c", "DEBIAN_FRONTEND=noninteractive dpkg-reconfigure keyboard-configuration"],
                phase="configure-keyboard",
            )
            self._chroot(["/bin/sh", "-c", "getent group xaac-admin >/dev/null || groupadd --system xaac-admin"], phase="configure-group-admin")
            self._chroot(["/bin/sh", "-c", "getent group xaac-kiosk >/dev/null || groupadd --system xaac-kiosk"], phase="configure-group-kiosk")
            self._chroot([
                "/bin/sh", "-c",
                "id xaac-admin >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "
                "--gid xaac-admin --groups sudo xaac-admin",
            ], phase="configure-user-admin")
            self._chroot([
                "/bin/sh", "-c",
                "id xaac-kiosk >/dev/null 2>&1 || useradd --system --home-dir /var/lib/xaac-kiosk "
                "--create-home --shell /usr/sbin/nologin --gid xaac-kiosk xaac-kiosk",
            ], phase="configure-user-kiosk")
            # greetd launches the dedicated session directly; the kiosk account
            # must never expose an interactive login shell.
            self._chroot(["usermod", "--shell", "/usr/sbin/nologin", "xaac-kiosk"], phase="configure-shell-kiosk")
            self._chroot(["passwd", "--lock", "root"], phase="configure-lock-root")
            self._chroot(["passwd", "--lock", "xaac-admin"], phase="configure-lock-admin")
            self._chroot(["passwd", "--lock", "xaac-kiosk"], phase="configure-lock-kiosk")
            self._configure_freerdp_certificate_store()
            if debs:
                self._chroot([
                    "apt-get", "install", "--yes", "--no-install-recommends",
                    "-o", "Dpkg::Options::=--force-confdef",
                    "-o", "Dpkg::Options::=--force-confold",
                    *debs,
                ], phase="configure-xaac-packages")
            self._chroot([
                "/bin/sh", "-ec",
                "test \"$(dpkg-query -W -f='${Status}' xaac-agent)\" = 'install ok installed'; "
                f"test \"$(dpkg-query -W -f='${{Version}}' xaac-agent)\" = '{agent_debian_version}'; "
                "test -x /opt/xaac-agent/runtime/bin/python3.13; "
                "test -x /opt/xaac-agent/runtime/bin/xaac-agent; "
                "test -x /opt/xaac-agent/runtime/bin/xaac-agent-admin; "
                "test -x /usr/sbin/xaac-agent-admin; "
                "test \"$(readlink /usr/sbin/xaac-agent-admin)\" = '/opt/xaac-agent/runtime/bin/xaac-agent-admin'; "
                "test -f /etc/xaac-agent/agent.ini; "
                "test -f /usr/lib/systemd/system/xaac-agent.service; "
                "test -f /usr/lib/systemd/system/xaac-privileged-helper.socket; "
                "getent passwd xaac-agent >/dev/null; "
                "getent group xaac-command >/dev/null; "
                "getent group xaac-ipc >/dev/null; "
                "id -nG xaac-agent | tr ' ' '\\n' | grep -Fx xaac-command >/dev/null; "
                "id -nG xaac-agent | tr ' ' '\\n' | grep -Fx xaac-ipc >/dev/null; "
                "grep -F 'd /run/xaac-agent 0750 root xaac-command -' /usr/lib/tmpfiles.d/xaac-agent.conf >/dev/null; "
                "grep -F 'd /run/xaac-agent/runtime 0700 xaac-agent xaac-agent -' /usr/lib/tmpfiles.d/xaac-agent.conf >/dev/null; "
                "grep -F 'CapabilityBoundingSet=CAP_SYS_BOOT' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null; "
                "grep -Fx 'ReadWritePaths=/etc/xaac' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null; "
                "grep -Fx 'LoadCredential=xaac-enrollment-token:-/etc/xaac-agent/enrollment.token' /usr/lib/systemd/system/xaac-agent.service >/dev/null; "
                "! test -e /etc/xaac-agent/enrollment.token; "
                "! grep -F 'CAP_SYS_ADMIN' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null; "
                "! systemctl is-enabled --quiet xaac-agent.service; "
                "systemctl is-enabled --quiet xaac-privileged-helper.socket",
            ], phase="configure-verify-xaac-agent")
            try:
                XmsEnrollmentManager(
                    self.paths.rootfs,
                    self.paths.project_root / "config/xms-enrollment.yaml",
                ).install()
            except XmsEnrollmentError as exc:
                raise ProductionBuildError(f"Contracte d'enrolament XMS invàlid: {exc}") from exc
            self._chroot([
                "/bin/sh", "-ec",
                "test -f /etc/xaac/xms-enrollment-manifest.json; "
                "grep -F 'xaac-agent-admin/v1' /etc/xaac/xms-enrollment-manifest.json >/dev/null; "
                "grep -F 'accepted_cli_secret_argument' /etc/xaac/xms-enrollment-manifest.json | grep -F 'false' >/dev/null; "
                "! grep -Ei 'credential[^s]|password|otp|private.key' /etc/xaac/xms-enrollment-manifest.json >/dev/null",
            ], phase="configure-xaac-xms-enrollment")

            self._chroot([
                "/bin/sh", "-ec",
                "usermod --append --groups xaac-ipc xaac-kiosk; "
                "id -nG xaac-kiosk | tr ' ' '\\n' | grep -Fx xaac-ipc >/dev/null",
            ], phase="configure-xaac-ipc-membership")
            try:
                LocalIntegrationConfigurator().install(
                    self.paths.rootfs,
                    self.paths.project_root / "config/local-integration.yaml",
                )
            except LocalIntegrationError as exc:
                raise ProductionBuildError(f"Contracte local OS-Agent invàlid: {exc}") from exc
            self._chroot([
                "/bin/sh", "-ec",
                # Only materialise persistent directories here. /run is bind-mounted
                # from the build host while configuring the chroot and is a tmpfs on
                # the target system, so creating/checking runtime paths here would
                # validate the host mount rather than the static image.
                "systemd-tmpfiles --create --prefix=/var/lib/xaac/thin-client /usr/lib/tmpfiles.d/xaac-local-integration.conf; "
                "test -d /var/lib/xaac/thin-client/state; "
                "test -d /var/lib/xaac/thin-client/config; "
                "test \"$(stat -c '%U:%G:%a' /var/lib/xaac/thin-client/state)\" = 'xaac-kiosk:xaac-ipc:2750'; "
                "test \"$(stat -c '%U:%G:%a' /var/lib/xaac/thin-client/config)\" = 'xaac-agent:xaac-ipc:2750'; "
                "test -f /usr/lib/tmpfiles.d/xaac-local-integration.conf; "
                "test -f /etc/xaac/local-integration-manifest.json",
            ], phase="configure-xaac-local-integration")
            # Block 5 invariant: the application package must be present in the
            # final rootfs.  Never produce a kiosk ISO that can only start the
            # compositor and then show a black screen.
            self._chroot([
                "/bin/sh", "-ec",
                "command -v xaac-thinclient >/dev/null; "
                "test \"$(dpkg-query -W -f='${Status}' xaac-thinclient)\" = 'install ok installed'; "
                "test \"$(dpkg-query -W -f='${Version}' xaac-thinclient)\" = '1.0.0'",
            ], phase="configure-verify-xaac-thinclient")
            self._verify_thinclient_rootfs(context="configure")
            # XAAC Thin Client VPN is installed exclusively from its .deb.
            self._chroot([
                "/bin/sh", "-ec",
                "test \"$(dpkg-query -W -f='${Status}' xaac-thin-client-vpn)\" = 'install ok installed'; "
                "command -v xaac-thin-client-vpn >/dev/null; "
                "test -f /lib/systemd/system/xaac-vpn-manager.service; "
                "getent group xaac-vpn >/dev/null || addgroup --system xaac-vpn; "
                "usermod --append --groups xaac-vpn xaac-kiosk",
            ], phase="configure-verify-xaac-vpn")
            vpn_gate_source = self.paths.project_root / "assets/runtime/xaac-vpn-session-gate"
            vpn_gate_target = self._inside("/usr/local/libexec/xaac-vpn-session-gate")
            vpn_gate_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(vpn_gate_source, vpn_gate_target)
            vpn_gate_target.chmod(0o755)

            vpn_admin_source = self.paths.project_root / "assets/runtime/xaac-vpn-admin"
            if not vpn_admin_source.is_file():
                raise ProductionBuildError("Falta assets/runtime/xaac-vpn-admin")
            vpn_admin_target = self._inside("/usr/local/sbin/xaac-vpn-admin")
            vpn_admin_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(vpn_admin_source, vpn_admin_target)
            vpn_admin_target.chmod(0o755)

            self._chroot(["systemctl", "enable", "xaac-vpn-manager.service"], phase="configure-enable-xaac-vpn")
            self._chroot(
                [
                    "/bin/sh", "-ec",
                    "chown root:root /etc/xaac/vpn-manager.toml; "
                    "chmod 0644 /etc/xaac/vpn-manager.toml; "
                    "test -x /usr/local/sbin/xaac-vpn-admin; "
                    "/usr/local/sbin/xaac-vpn-admin --help >/dev/null",
                ],
                phase="configure-vpn-config-permissions",
            )
            self._configure_production_kernel_resources()
            self._configure_production_network_hardening()
            self._configure_production_service_hardening()
            self._install_block9_target_validation()
            self._configure_update_architecture()
            self._configure_base_os_updates()
            self._configure_maintenance_diagnostics()
            self._configure_recovery_environment()
            self._install_block10_target_validation()
            self._configure_openvpn3_network()
            self._install_zorin_icon_theme()
            self._install_zorin_gtk_theme()
            self._customize_xaac_thinclient_theme()
            self._configure_xaac_thinclient_production_runtime()
            thinclient_deb = self.paths.project_root / "packages/xaac-thinclient_1.0.0_all.deb"
            if not thinclient_deb.is_file():
                raise ProductionBuildError("Falta packages/xaac-thinclient_1.0.0_all.deb")
            thinclient_sha = hashlib.sha256(thinclient_deb.read_bytes()).hexdigest()
            self._atomic_write(
                self._inside("/etc/xaac/block5-integration"),
                f"thinclient_package=xaac-thinclient\nversion=1.0.0\nsha256={thinclient_sha}\n",
            )
            # The .deb enables its user service globally for generic Debian
            # desktops.  XAAC Thin Client OS has its own bounded supervisor, so
            # disable the package's generic autostart to prevent duplicates.
            self._chroot([
                "/bin/sh", "-c",
                "systemctl --global disable xaac-thinclient.service >/dev/null 2>&1 || true",
            ], phase="configure-disable-generic-xaac-autostart")
            self._chroot(["systemctl", "enable", "NetworkManager.service"], phase="configure-networkmanager")
            self._chroot(["systemctl", "enable", "xaac-thinclient-language-sync.service"], phase="configure-thinclient-language-sync")
            self._chroot(["systemctl", "enable", "greetd.service"], phase="configure-greetd")
            self._chroot(["systemctl", "set-default", "graphical.target"], phase="configure-graphical-target")
            self._chroot(["systemctl", "enable", "xaac-installer-welcome.service"], phase="configure-installer-welcome")
            self._verify_block7_rootfs(context="configure")
            self._chroot(
                [
                    "/bin/sh", "-ec",
                    "apt-get clean; "
                    "rm -rf /var/lib/apt/lists/* /tmp/xaac-packages; "
                    "find /var/cache/apt/archives -maxdepth 1 -type f -name '*.deb' -delete",
                ],
                phase="configure-clean-build-cache",
            )
        with contextlib.suppress(FileNotFoundError):
            self._inside("/usr/sbin/policy-rc.d").unlink()
        self._save_state("configure")

    def phase_boot(self) -> None:
        self._require_root()
        with self._chroot_mounts():
            self._chroot(["update-initramfs", "-c", "-k", "all"], phase="boot-initramfs")
            kernels = sorted(self._inside("/boot").glob("vmlinuz-*"))
            if not kernels:
                raise ProductionBuildError("No s'ha trobat cap kernel dins del rootfs")
            kernel = kernels[-1]
            version = kernel.name.removeprefix("vmlinuz-")
            initrd = self._inside(f"/boot/initrd.img-{version}")
            if not initrd.is_file():
                raise ProductionBuildError(f"No s'ha generat l'initramfs: {initrd}")
            # A configured theme is not enough: if the Plymouth hook does not
            # copy the XAAC assets into initramfs, the early boot falls back to
            # a blank/generic console.  Fail the build before producing an ISO
            # when the appliance branding is missing from early userspace.
            self._chroot(
                [
                    "/bin/sh", "-ec",
                    f"lsinitramfs /boot/initrd.img-{version} | grep -Fx 'usr/share/plymouth/themes/xaac/xaac.plymouth' >/dev/null; "
                    f"lsinitramfs /boot/initrd.img-{version} | grep -Fx 'usr/share/plymouth/themes/xaac/xaac.script' >/dev/null; "
                    f"lsinitramfs /boot/initrd.img-{version} | grep -Fx 'usr/share/plymouth/themes/xaac/XAAC_TC_OS.png' >/dev/null; "
                    f"lsinitramfs /boot/initrd.img-{version} | grep -Fx 'usr/share/plymouth/themes/xaac/XAAC_loading_0.png' >/dev/null; "
                    f"lsinitramfs /boot/initrd.img-{version} | grep -Fx 'usr/share/plymouth/themes/xaac/XAAC_loading_1.png' >/dev/null; "
                    f"lsinitramfs /boot/initrd.img-{version} | grep -Fx 'usr/share/plymouth/themes/xaac/XAAC_loading_2.png' >/dev/null; "
                    f"lsinitramfs /boot/initrd.img-{version} | grep -Eq '/i915\\.ko(\\.(xz|zst|gz))?$'",
                ],
                phase="boot-verify-xaac-plymouth",
            )
        boot_dir = self.paths.build_root / "boot"
        boot_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kernel, boot_dir / "vmlinuz")
        shutil.copy2(initrd, boot_dir / "initrd.img")
        self._save_state("boot")

    def phase_squashfs(self) -> None:
        self._require_root()
        self.cleanup_chroot_mounts()
        self._assert_chroot_unmounted("generació del squashfs")
        self._verify_thinclient_rootfs(context="pre-squashfs")
        self._verify_block7_rootfs(context="pre-squashfs")
        output = self.paths.build_root / "rootfs.squashfs"
        output.unlink(missing_ok=True)
        self.runner.run([
            "mksquashfs", str(self.paths.rootfs), str(output),
            "-comp", "xz", "-b", "1M", "-noappend", "-no-progress",
            "-e", "boot",
        ], phase="squashfs")
        if not self.dry_run:
            self.runner.run([
                "unsquashfs", "-cat", str(output), "usr/bin/xaac-thinclient"
            ], phase="squashfs-verify-xaac-thinclient")
            self.runner.run([
                "unsquashfs", "-cat", str(output), "etc/xaac/block5-integration"
            ], phase="squashfs-verify-block5-marker")
        self._save_state("squashfs")

    def phase_iso(self) -> None:
        self._require_root()
        kernel = self.paths.build_root / "boot/vmlinuz"
        initrd = self.paths.build_root / "boot/initrd.img"
        squashfs = self.paths.build_root / "rootfs.squashfs"
        for source in (kernel, initrd, squashfs):
            if not source.is_file():
                raise ProductionBuildError(f"Falta l'artefacte previ: {source}")
        if self.paths.staging.exists():
            shutil.rmtree(self.paths.staging)
        (self.paths.staging / "live").mkdir(parents=True)
        (self.paths.staging / "boot/grub").mkdir(parents=True)
        (self.paths.staging / "install").mkdir(parents=True)
        shutil.copy2(kernel, self.paths.staging / "live/vmlinuz")
        shutil.copy2(initrd, self.paths.staging / "live/initrd.img")
        shutil.copy2(squashfs, self.paths.staging / "live/filesystem.squashfs")
        installer = self.paths.project_root / "builder/scripts/xaac-installer"
        if installer.is_file():
            shutil.copy2(installer, self.paths.staging / "install/xaac-installer")
            os.chmod(self.paths.staging / "install/xaac-installer", 0o755)
        # live-boot is retained solely to locate and mount filesystem.squashfs.
        # User creation, autologin and installer dispatch are entirely owned by
        # the rootfs and systemd units generated by XAAC. Do not pass
        # ``components`` or any live-config identity parameters.
        params = " ".join(("boot=live", *self.settings.kernel_parameters))
        diagnostics = " ".join(("boot=live", "ro", "toram", "xaac.mode=diagnostics", *self.settings.kernel_parameters))
        self._atomic_write(
            self.paths.staging / "boot/grub/grub.cfg",
            "# XAAC Thin Client OS production media\n"
            "# Normal boot is intentionally menu-less. Press Esc during this\n"
            "# short window to expose the read-only diagnostics entry.\n"
            "set default=0\n"
            "set timeout_style=hidden\n"
            "set timeout=2\n\n"
            "menuentry 'Install XAAC Thin Client OS' {\n"
            f"  linux /live/vmlinuz {params} xaac.mode=installer systemd.unit=multi-user.target\n"
            "  initrd /live/initrd.img\n}\n\n"
            "menuentry 'XAAC diagnostics (read-only)' {\n"
            f"  linux /live/vmlinuz {diagnostics}\n"
            "  initrd /live/initrd.img\n}\n",
        )
        self.paths.artifacts.mkdir(parents=True, exist_ok=True)
        iso = self.paths.artifacts / self.settings.output_name
        iso.unlink(missing_ok=True)
        # grub-mkrescue already invokes xorriso with the correct emulation.
        # Passing ``-- -V <label>`` forwards ``-V`` to xorriso's native
        # command mode, where it is not valid, and causes the build to fail.
        self.runner.run(
            ["grub-mkrescue", "-o", str(iso), str(self.paths.staging)],
            phase="iso-grub-mkrescue",
        )
        self._save_state("iso")

    def phase_verify(self) -> None:
        iso = self.paths.artifacts / self.settings.output_name
        if not iso.is_file() or iso.stat().st_size == 0:
            raise ProductionBuildError(f"La ISO no existeix o és buida: {iso}")
        digest = hashlib.sha256()
        with iso.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        iso_sha256 = digest.hexdigest()
        checksum = iso.with_suffix(iso.suffix + ".sha256")
        self._atomic_write(checksum, f"{iso_sha256}  {iso.name}\n")
        self.runner.run(["sha256sum", "-c", checksum.name], phase="verify-sha256", cwd=iso.parent)

        squashfs = self.paths.build_root / "rootfs.squashfs"
        squashfs_sha256 = None
        squashfs_size = None
        if squashfs.is_file():
            squashfs_digest = hashlib.sha256()
            with squashfs.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    squashfs_digest.update(chunk)
            squashfs_sha256 = squashfs_digest.hexdigest()
            squashfs_size = squashfs.stat().st_size

        update_keyring = self.paths.rootfs / "usr/share/keyrings/xaac-archive-keyring.gpg"
        manifest = {
            "schema": "xaac-block10-release-manifest/v1",
            "product": "XAAC Thin Client OS",
            "version": self.settings.version,
            "profile": self.settings.profile,
            "channel": self.settings.channel,
            "architecture": self.settings.architecture,
            "iso": {
                "name": iso.name,
                "size_bytes": iso.stat().st_size,
                "sha256": iso_sha256,
            },
            "squashfs": {
                "size_bytes": squashfs_size,
                "sha256": squashfs_sha256,
            },
            "lifecycle": {
                "update_model": "xaac-update-manifest/v1",
                "transactional_update": True,
                "automatic_rollback": True,
                "controlled_base_os_update": True,
                "base_os_suite": "trixie",
                "automatic_base_os_update": False,
                "base_os_full_upgrade_allowed": False,
                "boot_recovery": True,
                "factory_reset_enabled": False,
                "release_keyring_provisioned": (
                    update_keyring.is_file() and update_keyring.stat().st_size > 0
                ),
            },
            "validation": {
                "pre_iso_gate": "./scripts/validate-block10-release.sh",
                "target_command": "sudo /usr/local/sbin/xaac-block10-validate",
                "block9_target_command": "sudo /usr/local/sbin/xaac-block9-validate",
                "apparmor_mode": "complain-review-required",
                "physical_validation_required": True,
                "qualification_cycle": ["install", "update", "rollback", "update"],
            },
        }
        manifest_path = iso.with_suffix(iso.suffix + ".release.json")
        self._atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        self._save_state("verify")

    def run(self, phases: Iterable[str]) -> Path:
        selected = tuple(phases)
        invalid = sorted(set(selected) - set(self.PHASES))
        if invalid:
            raise ProductionBuildError(f"Fases desconegudes: {', '.join(invalid)}")
        methods = {
            "rootfs": self.phase_rootfs,
            "configure": self.phase_configure,
            "boot": self.phase_boot,
            "squashfs": self.phase_squashfs,
            "iso": self.phase_iso,
            "verify": self.phase_verify,
        }
        for phase in selected:
            print(f"[XAAC] Fase {phase}...", flush=True)
            methods[phase]()
        return self.paths.artifacts / self.settings.output_name


def _restore_owner(path: Path) -> None:
    uid = os.environ.get("SUDO_UID")
    gid = os.environ.get("SUDO_GID")
    if uid is None or gid is None or not path.exists():
        return
    subprocess.run(["chown", "-R", f"{uid}:{gid}", str(path)], check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Constructor ISO per fases de XAAC Thin Client OS")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Arrel del projecte")
    parser.add_argument("--dry-run", action="store_true", help="Planifica sense executar ordres destructives")
    parser.add_argument("--clean", action="store_true", help="Neteja el workspace de producció abans de construir")
    parser.add_argument(
        "--cleanup-mounts-only", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--phase", action="append", choices=ProductionIsoBuilder.PHASES,
        help="Executa només aquesta fase; es pot repetir",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        builder = ProductionIsoBuilder(args.root, dry_run=args.dry_run)
        if args.cleanup_mounts_only:
            builder.cleanup_chroot_mounts()
            return 0
        if args.clean:
            builder.clean()
        phases = tuple(args.phase) if args.phase else ProductionIsoBuilder.PHASES
        iso = builder.run(phases)
        if not args.dry_run and "verify" in phases:
            print(f"ISO generada correctament: {iso}")
        return 0
    except KeyboardInterrupt:
        print("error: construcció interrompuda", file=sys.stderr)
        return 130
    except (ProductionBuildError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            if "builder" in locals():
                builder.cleanup_chroot_mounts()
            root = BuildPaths.create(args.root)
            _restore_owner(root.project_root / ".build")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
