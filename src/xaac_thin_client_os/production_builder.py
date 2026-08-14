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
            "socat",
            "fonts-roboto",
            "nano",
            "adwaita-icon-theme",
            "adwaita-icon-theme-legacy",
            "hicolor-icon-theme",
        }
        packages = tuple(sorted(set(resolved.packages).union(mandatory)))
        kernel_parameters: list[str] = []
        for profile_name in resolved.profile_chain:
            profile_raw = yaml_mapping(f"profiles/{profile_name}/profile.yaml")
            values = profile_raw.get("kernel_parameters", [])
            if isinstance(values, list):
                kernel_parameters.extend(str(value) for value in values if value)

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
            kernel_parameters=tuple(dict.fromkeys(kernel_parameters)),
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

    def _validate_xaac_agent_artifact(self) -> None:
        try:
            create_xaac_agent_plan(
                self.paths.rootfs,
                self.paths.project_root,
                self.paths.project_root / "config/xaac-agent-package.yaml",
            )
        except XaacAgentPackageError as exc:
            raise ProductionBuildError(f"Paquet XAAC Agent invàlid: {exc}") from exc

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
        sources = (
            f"deb {mirror} {suite} {components}\n"
            f"deb {mirror} {suite}-updates {components}\n"
            f"deb https://security.debian.org/debian-security {suite}-security {components}\n"
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
            self._inside("/etc/systemd/system/greetd.service.d/10-xaac-mode.conf"),
            "[Unit]\nConditionKernelCommandLine=!xaac.mode=installer\n",
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

        self._atomic_write(
            self._inside("/usr/local/sbin/xaac-kiosk-poweroff"),
            "#!/bin/sh\nset -eu\nexec /usr/bin/systemctl poweroff\n",
            0o755,
        )
        self._atomic_write(
            self._inside("/usr/local/sbin/xaac-kiosk-reboot"),
            "#!/bin/sh\nset -eu\nexec /usr/bin/systemctl reboot\n",
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

        theme_dir = self._inside("/usr/share/plymouth/themes/xaac")
        theme_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, theme_dir / "XAAC_TC_OS.png")
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
            "Window.SetBackgroundTopColor(1.0, 1.0, 1.0);\n"
            "Window.SetBackgroundBottomColor(1.0, 1.0, 1.0);\n\n"
            "screen_width = Window.GetWidth();\n"
            "screen_height = Window.GetHeight();\n"
            "image = Image(\"XAAC_TC_OS.png\");\n"
            "image_width = image.GetWidth();\n"
            "image_height = image.GetHeight();\n"
            "scale_x = screen_width / image_width;\n"
            "scale_y = screen_height / image_height;\n"
            "scale = scale_x;\n"
            "if (scale_y < scale_x)\n"
            "  scale = scale_y;\n"
            "scaled_width = image_width * scale;\n"
            "scaled_height = image_height * scale;\n"
            "image = image.Scale(scaled_width, scaled_height);\n"
            "sprite = Sprite(image);\n"
            "sprite.SetX((screen_width - scaled_width) / 2);\n"
            "sprite.SetY((screen_height - scaled_height) / 2);\n"
            "sprite.SetZ(10000);\n",
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
            "ExecStart=/bin/sh -c 'printf \"\\033[2J\\033[H\\033[3J\" > /dev/tty1'\n\n"
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
            'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=0 systemd.log_level=emerg systemd.show_status=0 '
            'rd.systemd.show_status=0 vt.global_cursor_default=0 udev.log_priority=3 '
            'plymouth.ignore-serial-consoles"\n',
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
        self._atomic_write(
            self._inside("/usr/local/sbin/xaac-installer-welcome"),
            "#!/bin/sh\n"
            "set -eu\n"
            "clear\n"
            "printf '%s\\n' 'XAAC Thin Client OS — Instal·lador (pas 5)'\n"
            "printf '%s\\n' '============================================'\n"
            "printf '\\n'\n"
            "printf '%s\\n' 'Preflight, particionat GPT, format i desplegament del sistema base.'\n"
            "printf '%s\\n' 'ATENCIÓ: aquest pas elimina totes les dades del disc seleccionat.'\n"
            "printf '\\n'\n"
            "disks_file=$(mktemp)\n"
            "trap 'rm -f \"$disks_file\"' EXIT HUP INT TERM\n"
            "lsblk -bdnP -o NAME,SIZE,MODEL,TYPE,RO,RM | while IFS= read -r line; do\n"
            "    eval \"$line\"\n"
            "    [ \"${TYPE:-}\" = disk ] || continue\n"
            "    [ \"${RO:-1}\" = 0 ] || continue\n"
            "    base=${NAME##*/}\n"
            "    case $base in loop*|ram*|zram*|sr*) continue ;; esac\n"
            "    printf '%s\\t%s\\t%s\\t%s\\n' \"$NAME\" \"$SIZE\" \"${MODEL:-}\" \"${RM:-0}\"\n"
            "done > \"$disks_file\"\n"
            "if [ ! -s \"$disks_file\" ]; then\n"
            "    printf '%s\\n' 'No s’ha detectat cap disc escrivible.'\n"
            "    printf '%s' 'Premeu Retorn per reiniciar el sistema: '\n"
            "    IFS= read -r _answer\n"
            "    systemctl reboot\n"
            "fi\n"
            "printf '%s\\n' 'Discs detectats:'\n"
            "printf '\\n'\n"
            "i=1\n"
            "while IFS='\\t' read -r name size_bytes model removable; do\n"
            "    [ -n \"$model\" ] || model='Model no informat'\n"
            "    size_human=$(numfmt --to=iec-i --suffix=B \"$size_bytes\" 2>/dev/null || printf '%s bytes' \"$size_bytes\")\n"
            "    kind=intern\n"
            "    [ \"$removable\" = 0 ] || kind=extraïble\n"
            "    printf '  %s) %-14s %-9s %-10s %s\\n' \"$i\" \"$name\" \"$size_human\" \"$kind\" \"$model\"\n"
            "    i=$((i + 1))\n"
            "done < \"$disks_file\"\n"
            "printf '\\n'\n"
            "count=$(wc -l < \"$disks_file\" | tr -d ' ')\n"
            "while :; do\n"
            "    printf '%s' 'Seleccioneu el número del disc: '\n"
            "    IFS= read -r choice\n"
            "    case $choice in\n"
            "        ''|*[!0-9]*) printf '%s\\n' 'Selecció no vàlida.' ; continue ;;\n"
            "    esac\n"
            "    if [ \"$choice\" -ge 1 ] 2>/dev/null && [ \"$choice\" -le \"$count\" ]; then\n"
            "        break\n"
            "    fi\n"
            "    printf '%s\\n' 'Selecció fora de rang.'\n"
            "done\n"
            "selected=$(sed -n \"${choice}p\" \"$disks_file\")\n"
            "selected_name=$(printf '%s\\n' \"$selected\" | cut -f1)\n"
            "selected_size=$(printf '%s\\n' \"$selected\" | cut -f2)\n"
            "selected_model=$(printf '%s\\n' \"$selected\" | cut -f3)\n"
            "selected_rm=$(printf '%s\\n' \"$selected\" | cut -f4)\n"
            "target=/dev/$selected_name\n"
            "case $target in /dev/*) ;; *) printf '%s\\n' 'Dispositiu de destinació no vàlid.'; exit 1 ;; esac\n"
            "[ -b \"$target\" ] || { printf '%s\\n' 'El disc seleccionat ja no existeix.'; exit 1; }\n"
            "current_size=$(lsblk -bdno SIZE \"$target\" | tr -d ' ')\n"
            "[ \"$current_size\" = \"$selected_size\" ] || { printf '%s\\n' 'El disc ha canviat des de la detecció.'; exit 1; }\n"
            "minimum_size=7000000000\n"
            "if [ \"$selected_size\" -lt \"$minimum_size\" ]; then\n"
            "    printf '%s\\n' 'El disc és massa petit per instal·lar XAAC Thin Client OS.'\n"
            "    exit 1\n"
            "fi\n"
            "if lsblk -nrpo MOUNTPOINT \"$target\" | grep -q '[^[:space:]]'; then\n"
            "    printf '%s\\n' 'El disc o alguna partició està muntada. Instal·lació rebutjada.'\n"
            "    exit 1\n"
            "fi\n"
            "if [ \"$selected_rm\" != 0 ]; then\n"
            "    printf '%s\\n' 'Advertència: el dispositiu seleccionat està marcat com a extraïble.'\n"
            "fi\n"
            "size_human=$(numfmt --to=iec-i --suffix=B \"$selected_size\" 2>/dev/null || printf '%s bytes' \"$selected_size\")\n"
            "printf '\\n'\n"
            "printf '%s\\n' 'RESUM DE L’OPERACIÓ DESTRUCTIVA'\n"
            "printf '  Dispositiu: %s\\n' \"$target\"\n"
            "printf '  Capacitat:  %s\\n' \"$size_human\"\n"
            "printf '  Model:      %s\\n' \"${selected_model:-Model no informat}\"\n"
            "printf '\\n'\n"
            "printf '%s\\n' 'Totes les dades d’aquest disc s’eliminaran immediatament després de confirmar.'\n"
            "printf '%s\\n' 'Per confirmar la selecció escriviu exactament: INSTALL XAAC'\n"
            "printf '%s' '> '\n"
            "IFS= read -r confirmation\n"
            "if [ \"$confirmation\" != 'INSTALL XAAC' ]; then\n"
            "    printf '%s\\n' 'Confirmació incorrecta. No s’ha fet cap canvi.'\n"
            "    printf '%s' 'Premeu Retorn per reiniciar el sistema: '\n"
            "    IFS= read -r _answer\n"
            "    systemctl reboot\n"
            "fi\n"
            "printf '\\n'\n"
            "printf '%s\\n' 'Confirmació acceptada.'\n"
            "printf '\\n%s\\n' 'Configureu ara la contrasenya de l’administrador local xaac-admin.'\n"
            "printf '%s\\n' 'Ha de tindre almenys 12 caràcters i no pot contindre dos punts (:).'\n"
            "trap 'stty echo 2>/dev/null || true; exit 130' HUP INT TERM\n"
            "while :; do\n"
            "    printf '%s' 'Contrasenya: '\n"
            "    stty -echo\n"
            "    IFS= read -r admin_password || { stty echo; printf '\\n'; exit 1; }\n"
            "    stty echo\n"
            "    printf '\\n%s' 'Repetiu la contrasenya: '\n"
            "    stty -echo\n"
            "    IFS= read -r admin_password_confirm || { stty echo; printf '\\n'; exit 1; }\n"
            "    stty echo\n"
            "    printf '\\n'\n"
            "    [ \"$admin_password\" = \"$admin_password_confirm\" ] || { printf '%s\\n' 'Les contrasenyes no coincideixen.'; continue; }\n"
            "    [ \"${#admin_password}\" -ge 12 ] || { printf '%s\\n' 'La contrasenya és massa curta.'; continue; }\n"
            "    case $admin_password in *:*) printf '%s\\n' 'La contrasenya no pot contindre dos punts (:).'; continue ;; esac\n"
            "    break\n"
            "done\n"
            "trap - HUP INT TERM\n"
            "unset admin_password_confirm\n"
            "printf '\n%s\n' 'Configureu el nom de la màquina.'\n"
            "while :; do\n"
            "    printf '%s' 'Hostname [xaac-thin-client]: '\n"
            "    IFS= read -r install_hostname\n"
            "    [ -n \"$install_hostname\" ] || install_hostname=xaac-thin-client\n"
            "    case $install_hostname in *[!A-Za-z0-9-]*|-*|*-) printf '%s\n' 'Hostname no vàlid.'; continue ;; esac\n"
            "    [ \"${#install_hostname}\" -le 63 ] || { printf '%s\n' 'Hostname massa llarg.'; continue; }\n"
            "    break\n"
            "done\n"
            "printf '\n%s\n' 'Configureu el servidor RDP principal.'\n"
            "while :; do\n"
            "    printf '%s' 'Servidor RDP (nom DNS o IP): '\n"
            "    IFS= read -r install_rdp_host\n"
            "    [ -n \"$install_rdp_host\" ] || { printf '%s\n' 'El servidor RDP no pot estar buit.'; continue; }\n"
            "    case $install_rdp_host in *[!A-Za-z0-9.:-]*) printf '%s\n' 'Servidor RDP no vàlid.'; continue ;; esac\n"
            "    break\n"
            "done\n"
            "while :; do\n"
            "    printf '%s' 'Domini RDP: '\n"
            "    IFS= read -r install_rdp_domain\n"
            "    [ -n \"$install_rdp_domain\" ] || { printf '%s\n' 'El domini RDP no pot estar buit.'; continue; }\n"
            "    break\n"
            "done\n"
            "printf '%s\n' 'La xarxa Ethernet es configurarà automàticament per DHCP.'\n"
            "printf '%s\\n' 'Contrasenya administrativa validada. Comença la instal·lació.'\n"
            "live_source=$(findmnt -nro SOURCE /run/live/medium 2>/dev/null || true)\n"
            "if [ -n \"$live_source\" ]; then\n"
            "    live_parent=$(lsblk -ndo PKNAME \"$live_source\" 2>/dev/null | head -n1)\n"
            "    [ -n \"$live_parent\" ] || live_parent=${live_source#/dev/}\n"
            "    [ \"$target\" != \"/dev/$live_parent\" ] || { printf '%s\\n' 'El disc seleccionat conté el sistema Live actiu. Instal·lació rebutjada.'; exit 1; }\n"
            "fi\n"
            "ac_found=0; ac_online=0\n"
            "for supply in /sys/class/power_supply/*; do\n"
            "    [ -e \"$supply/type\" ] || continue\n"
            "    case $(cat \"$supply/type\" 2>/dev/null || true) in Mains|USB|USB_C) ac_found=1 ;; *) continue ;; esac\n"
            "    [ \"$(cat \"$supply/online\" 2>/dev/null || printf 0)\" = 1 ] && ac_online=1\n"
            "done\n"
            "if [ \"$ac_found\" = 1 ] && [ \"$ac_online\" != 1 ]; then printf '%s\\n' 'No s’ha detectat alimentació externa. Instal·lació rebutjada.'; exit 1; fi\n"
            "case $target in *[0-9]) p1=${target}p1; p2=${target}p2; p3=${target}p3; p4=${target}p4 ;; *) p1=${target}1; p2=${target}2; p3=${target}3; p4=${target}4 ;; esac\n"
            "mount_root=/mnt/xaac-target\n"
            "cleanup_install() {\n"
            "    sync || true\n"
            "    for mounted in \"$mount_root/run\" \"$mount_root/sys\" \"$mount_root/proc\" \"$mount_root/dev\" \"$mount_root/boot/efi\" \"$mount_root/data\" \"$mount_root/recovery\" \"$mount_root\"; do\n"
            "        mountpoint -q \"$mounted\" && umount \"$mounted\" || true\n"
            "    done\n"
            "}\n"
            "trap cleanup_install EXIT HUP INT TERM\n"
            "printf '%s\\n' '[1/5] Creant la taula GPT i les particions...'\n"
            "wipefs -a \"$target\"\n"
            "sgdisk --zap-all \"$target\"\n"
            "sgdisk -n 1:0:+256M -t 1:ef00 -c 1:XAAC_EFI \"$target\"\n"
            "sgdisk -n 2:0:+4096M -t 2:8300 -c 2:XAAC_ROOT \"$target\"\n"
            "sgdisk -n 3:0:+1024M -t 3:8300 -c 3:XAAC_DATA \"$target\"\n"
            "sgdisk -n 4:0:0 -t 4:8300 -c 4:XAAC_RECOVERY \"$target\"\n"
            "partprobe \"$target\"; udevadm settle\n"
            "for partition in \"$p1\" \"$p2\" \"$p3\" \"$p4\"; do [ -b \"$partition\" ] || { printf 'No s’ha creat %s\\n' \"$partition\"; exit 1; }; done\n"
            "printf '%s\\n' '[2/5] Creant els sistemes de fitxers...'\n"
            "mkfs.vfat -F 32 -n XAAC_EFI \"$p1\"\n"
            "mkfs.ext4 -F -L XAAC_ROOT \"$p2\"\n"
            "mkfs.ext4 -F -L XAAC_DATA \"$p3\"\n"
            "mkfs.ext4 -F -L XAAC_RECOVERY \"$p4\"\n"
            "printf '%s\\n' '[3/5] Muntant la destinació...'\n"
            "mkdir -p \"$mount_root\"; mount \"$p2\" \"$mount_root\"\n"
            "mkdir -p \"$mount_root/boot/efi\" \"$mount_root/data\" \"$mount_root/recovery\"\n"
            "mount \"$p1\" \"$mount_root/boot/efi\"; mount \"$p3\" \"$mount_root/data\"; mount \"$p4\" \"$mount_root/recovery\"\n"
            "printf '%s\\n' '[4/5] Desplegant el sistema base...'\n"
            "rootfs_image=/run/live/medium/live/filesystem.squashfs\n"
            "[ -r \"$rootfs_image\" ] || { printf '%s\\n' 'No s’ha trobat filesystem.squashfs al mitjà Live.'; exit 1; }\n"
            "unsquashfs -f -d \"$mount_root\" \"$rootfs_image\"\n"
            "printf '%s\\n' '[5/9] Instal·lant el nucli i l’initramfs al sistema de destinació...'\n"
            'kernel_version=$(find "$mount_root/lib/modules" -mindepth 1 -maxdepth 1 -type d -printf \'%f\\n\' | sort -V | tail -n1)\n'
            '[ -n "$kernel_version" ] || { printf \'%s\\n\' \'No s’ha pogut determinar la versió del nucli instal·lat.\'; exit 1; }\n'
            '[ -r /run/live/medium/live/vmlinuz ] || { printf \'%s\\n\' \'No s’ha trobat el nucli del mitjà Live.\'; exit 1; }\n'
            '[ -r /run/live/medium/live/initrd.img ] || { printf \'%s\\n\' \'No s’ha trobat l’initramfs del mitjà Live.\'; exit 1; }\n'
            'mkdir -p "$mount_root/boot"\n'
            'install -m 0644 /run/live/medium/live/vmlinuz "$mount_root/boot/vmlinuz-$kernel_version"\n'
            'install -m 0644 /run/live/medium/live/initrd.img "$mount_root/boot/initrd.img-$kernel_version"\n'
            'ln -sfn "vmlinuz-$kernel_version" "$mount_root/boot/vmlinuz"\n'
            'ln -sfn "initrd.img-$kernel_version" "$mount_root/boot/initrd.img"\n'
            '[ -s "$mount_root/boot/vmlinuz-$kernel_version" ] && [ -s "$mount_root/boot/initrd.img-$kernel_version" ] || { printf \'%s\\n\' \'El nucli o l’initramfs no han quedat instal·lats a /boot.\'; exit 1; }\n'
            "printf '%s\\n' '[6/9] Generant la configuració de muntatge...'\n"
            'root_uuid=$(blkid -s UUID -o value "$p2"); efi_uuid=$(blkid -s UUID -o value "$p1"); data_uuid=$(blkid -s UUID -o value "$p3"); recovery_uuid=$(blkid -s UUID -o value "$p4")\n'
            '[ -n "$root_uuid" ] && [ -n "$efi_uuid" ] && [ -n "$data_uuid" ] && [ -n "$recovery_uuid" ] || { printf \'%s\\n\' \'No s’han pogut obtindre tots els UUID.\'; exit 1; }\n'
            'cat > "$mount_root/etc/fstab" <<EOF\n'
            'UUID=$root_uuid / ext4 defaults,noatime 0 1\n'
            'UUID=$efi_uuid /boot/efi vfat umask=0077 0 1\n'
            'UUID=$data_uuid /data ext4 defaults,noatime 0 2\n'
            'UUID=$recovery_uuid /recovery ext4 defaults,noatime 0 2\n'
            'EOF\n'
            "printf '%s\\n' '[7/9] Instal·lant GRUB UEFI...'\n"
            'mkdir -p "$mount_root/dev" "$mount_root/proc" "$mount_root/sys" "$mount_root/run"\n'
            'mount --rbind /dev "$mount_root/dev"; mount --make-rslave "$mount_root/dev"\n'
            'mount -t proc proc "$mount_root/proc"\n'
            'mount --rbind /sys "$mount_root/sys"; mount --make-rslave "$mount_root/sys"\n'
            'mount --rbind /run "$mount_root/run"; mount --make-rslave "$mount_root/run"\n'
            'mkdir -p "$mount_root/etc/default/grub.d" "$mount_root/etc/grub.d"\n'
            "cat > \"$mount_root/etc/default/grub.d/10-xaac-identity.cfg\" <<'EOF'\n"
            'GRUB_DISTRIBUTOR="XAAC Thin Client OS"\n'
            'GRUB_DISABLE_SUBMENU=y\n'
            'GRUB_TIMEOUT=0\n'
            'GRUB_TIMEOUT_STYLE=hidden\n'
            'GRUB_RECORDFAIL_TIMEOUT=0\n'
            'GRUB_DISABLE_RECOVERY=true\n'
            'GRUB_DISABLE_OS_PROBER=true\n'
            'GRUB_GFXPAYLOAD_LINUX=keep\n'
            'EOF\n'
            'cat > "$mount_root/etc/grub.d/09_xaac" <<EOF\n'
            '#!/bin/sh\n'
            "cat <<'XAAC_ENTRY'\n"
            "menuentry 'XAAC Thin Client OS' --class xaac --class gnu-linux --class gnu --class os {\n"
            '    insmod part_gpt\n'
            '    insmod ext2\n'
            '    search --no-floppy --fs-uuid --set=root $root_uuid\n'
            '    linux /boot/vmlinuz root=UUID=$root_uuid ro quiet splash loglevel=0 systemd.log_level=emerg systemd.show_status=0 rd.systemd.show_status=0 vt.global_cursor_default=0 udev.log_priority=3 plymouth.ignore-serial-consoles\n'
            '    initrd /boot/initrd.img\n'
            '}\n'
            'XAAC_ENTRY\n'
            'EOF\n'
            'chmod 0755 "$mount_root/etc/grub.d/09_xaac"\n'
            'chmod -x "$mount_root/etc/grub.d/10_linux"\n'
            'chroot "$mount_root" grub-install --target=x86_64-efi --efi-directory=/boot/efi --boot-directory=/boot --bootloader-id=XAAC --removable --no-nvram --recheck\n'
            'chroot "$mount_root" update-grub\n'
            'signed_shim="$mount_root/usr/lib/shim/shimx64.efi.signed"\n'
            'signed_grub="$mount_root/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed"\n'
            'signed_mok="$mount_root/usr/lib/shim/mmx64.efi.signed"\n'
            '[ -s "$signed_shim" ] || { printf \'%s\\n\' \'No s’ha trobat shimx64.efi signat.\'; exit 1; }\n'
            '[ -s "$signed_grub" ] || { printf \'%s\\n\' \'No s’ha trobat grubx64.efi signat.\'; exit 1; }\n'
            'mkdir -p "$mount_root/boot/efi/EFI/BOOT" "$mount_root/boot/efi/EFI/XAAC"\n'
            'install -m 0644 "$signed_shim" "$mount_root/boot/efi/EFI/BOOT/BOOTX64.EFI"\n'
            'install -m 0644 "$signed_grub" "$mount_root/boot/efi/EFI/BOOT/grubx64.efi"\n'
            'install -m 0644 "$signed_shim" "$mount_root/boot/efi/EFI/XAAC/shimx64.efi"\n'
            'install -m 0644 "$signed_grub" "$mount_root/boot/efi/EFI/XAAC/grubx64.efi"\n'
            'if [ -s "$signed_mok" ]; then install -m 0644 "$signed_mok" "$mount_root/boot/efi/EFI/BOOT/mmx64.efi"; install -m 0644 "$signed_mok" "$mount_root/boot/efi/EFI/XAAC/mmx64.efi"; fi\n'
            'cat > "$mount_root/boot/efi/EFI/BOOT/grub.cfg" <<EOF\n'
            'search --no-floppy --fs-uuid --set=root $root_uuid\n'
            'set prefix=(\\$root)/boot/grub\n'
            'configfile \\$prefix/grub.cfg\n'
            'EOF\n'
            'cp "$mount_root/boot/efi/EFI/BOOT/grub.cfg" "$mount_root/boot/efi/EFI/XAAC/grub.cfg"\n'
            '[ -s "$mount_root/boot/grub/grub.cfg" ] || { printf \'%s\\n\' \'No s’ha generat grub.cfg.\'; exit 1; }\n'
            "grep -Fq \"menuentry 'XAAC Thin Client OS'\" \"$mount_root/boot/grub/grub.cfg\" || { printf '%s\\n' 'grub.cfg no conté l’entrada XAAC Thin Client OS.'; exit 1; }\n"
            'grep -Eq "^[[:space:]]*linux[[:space:]]+.*vmlinuz" "$mount_root/boot/grub/grub.cfg" || { printf \'%s\\n\' \'grub.cfg no conté cap ordre linux per carregar el nucli.\'; exit 1; }\n'
            'grep -Eq "^[[:space:]]*initrd[[:space:]]+.*initrd" "$mount_root/boot/grub/grub.cfg" || { printf \'%s\\n\' \'grub.cfg no conté cap ordre initrd.\'; exit 1; }\n'
            'for efi_file in "$mount_root/boot/efi/EFI/BOOT/BOOTX64.EFI" "$mount_root/boot/efi/EFI/BOOT/grubx64.efi"; do [ -s "$efi_file" ] || { printf \'No existeix o està buit: %s\\n\' "$efi_file"; exit 1; }; [ "$(od -An -tx1 -N2 "$efi_file" | tr -d \' \\n\')" = 4d5a ] || { printf \'No és un executable PE/COFF vàlid: %s\\n\' "$efi_file"; exit 1; }; done\n'
            'grep -Fq "$root_uuid" "$mount_root/boot/efi/EFI/BOOT/grub.cfg" || { printf \'%s\\n\' \'El fallback GRUB no referencia l’UUID arrel.\'; exit 1; }\n'
            'sgdisk -i 1 "$target" | grep -Eqi \'EF00|EFI system partition\' || { printf \'%s\\n\' \'La primera partició no és una ESP GPT vàlida.\'; exit 1; }\n'
            'sync; umount "$mount_root/boot/efi"\n'
            'fsck.vfat -n "$p1" >/dev/null || { printf \'%s\\n\' \'La partició EFI FAT32 no supera la verificació.\'; exit 1; }\n'
            'mount "$p1" "$mount_root/boot/efi"\n'
            "printf '%s\\n' '[8/10] Configurant l’administrador local...'\n"
            'admin_hash=$(printf \'%s\' "$admin_password" | openssl passwd -6 -stdin)\n'
            'case "$admin_hash" in \'$6$\'*) ;; *) printf \'%s\\n\' \'No s’ha pogut generar el hash SHA-512 de xaac-admin.\'; exit 1 ;; esac\n'
            "printf 'xaac-admin:%s\\n' \"$admin_hash\" | chroot \"$mount_root\" chpasswd --encrypted\n"
            'chroot "$mount_root" usermod --unlock --shell /bin/bash xaac-admin\n'
            'chroot "$mount_root" chage -E -1 -I -1 -m 0 xaac-admin\n'
            'passwd_status=$(chroot "$mount_root" passwd -S xaac-admin 2>/dev/null | awk \'{print $2}\')\n'
            "shadow_password=$(awk -F: '$1 == \"xaac-admin\" {print $2}' \"$mount_root/etc/shadow\")\n"
            'admin_shell=$(chroot "$mount_root" getent passwd xaac-admin 2>/dev/null | cut -d: -f7)\n'
            '[ "$passwd_status" = P ] || { printf \'%s\\n\' \'No s’ha pogut activar la contrasenya de xaac-admin.\'; exit 1; }\n'
            '[ "$shadow_password" = "$admin_hash" ] || { printf \'%s\\n\' \'El hash de xaac-admin no ha quedat escrit al sistema de destinació.\'; exit 1; }\n'
            '[ "$admin_shell" = /bin/bash ] || { printf \'%s\\n\' \'La shell de xaac-admin no és interactiva.\'; exit 1; }\n'
            'printf \'%s\\n\' "$admin_password" | chroot "$mount_root" pamtester login xaac-admin authenticate >/dev/null 2>&1 || { printf \'%s\\n\' \'PAM ha rebutjat la contrasenya de xaac-admin.\'; exit 1; }\n'
            'chroot "$mount_root" mkdir -p /var/lib/xaac/admin\n'
            'chroot "$mount_root" install -o root -g xaac-admin -m 0640 /dev/null /var/lib/xaac/admin/password-changed\n'
            "printf '%s\\n' '[9/10] Consolidant el sistema instal·lat i preparant el primer arrencament...'\n"
            'printf \'%s\\n\' "$install_hostname" > "$mount_root/etc/hostname"\n'
            'printf \'127.0.0.1 localhost\\n127.0.1.1 %s\\n::1 localhost ip6-localhost ip6-loopback\\n\' "$install_hostname" > "$mount_root/etc/hosts"\n'
            'if [ -f "$mount_root/etc/xaac-thinclient/device.ini" ]; then sed -i "s/^device_name[[:space:]]*=.*/device_name = $install_hostname/" "$mount_root/etc/xaac-thinclient/device.ini"; fi\n'
            'if [ -f "$mount_root/etc/xaac-thinclient/servers.ini" ]; then sed -i "s/^host[[:space:]]*=.*/host = $install_rdp_host/; s/^domain[[:space:]]*=.*/domain = $install_rdp_domain/; s/^enabled[[:space:]]*=.*/enabled = true/" "$mount_root/etc/xaac-thinclient/servers.ini"; fi\n'
            'mkdir -p "$mount_root/etc/NetworkManager/system-connections"\n'
            'cat > "$mount_root/etc/NetworkManager/system-connections/xaac-wired.nmconnection" <<EOF\n'
            '[connection]\n'
            'id=XAAC Wired DHCP\n'
            'type=ethernet\n'
            'autoconnect=true\n'
            'match-device=type:ethernet\n'
            '\n'
            '[ipv4]\n'
            'method=auto\n'
            '\n'
            '[ipv6]\n'
            'method=auto\n'
            'EOF\n'
            'chmod 0600 "$mount_root/etc/NetworkManager/system-connections/xaac-wired.nmconnection"\n'
            'chroot "$mount_root" systemctl enable NetworkManager.service >/dev/null\n'
            'mkdir -p "$mount_root/etc/xaac" "$mount_root/var/lib/xaac/installation" "$mount_root/recovery/installer"\n'
            'cp "$mount_root/etc/os-release" "$mount_root/etc/xaac/os-release"\n'
            'rm -f "$mount_root/etc/systemd/system/multi-user.target.wants/xaac-installer-welcome.service"\n'
            'rm -f "$mount_root/etc/systemd/system/xaac-installer-welcome.service" "$mount_root/usr/local/sbin/xaac-installer-welcome"\n'
            'rm -rf "$mount_root/etc/systemd/system/getty@tty1.service.d"\n'
            'rm -f "$mount_root/etc/systemd/system/getty.target.wants/getty@tty1.service"\n'
            'ln -sfn /dev/null "$mount_root/etc/systemd/system/getty@tty1.service"\n'
            'chroot "$mount_root" usermod --shell /usr/sbin/nologin xaac-kiosk\n'
            'chroot "$mount_root" systemctl enable greetd.service >/dev/null\n'
            'chroot "$mount_root" systemctl set-default graphical.target >/dev/null\n'
            'rm -f "$mount_root/run/xaac-installer"* "$mount_root/tmp/xaac-installer"* 2>/dev/null || true\n'
            'printf "status=consolidated\\ninstaller_removed=yes\\nidentity=xaac-thin-client-os\\n" > "$mount_root/var/lib/xaac/installation/consolidated"\n'
            ': > "$mount_root/etc/machine-id"\n'
            'rm -f "$mount_root/var/lib/dbus/machine-id" "$mount_root"/etc/ssh/ssh_host_* "$mount_root/var/lib/systemd/random-seed"\n'
            'chroot "$mount_root" ssh-keygen -A\n'
            'test -s "$mount_root/etc/ssh/ssh_host_ed25519_key" || { printf \'%s\\n\' \'No s’ha generat la host key ED25519 d’OpenSSH.\'; exit 1; }\n'
            'test -s "$mount_root/etc/ssh/ssh_host_ed25519_key.pub" || { printf \'%s\\n\' \'No s’ha generat la host key pública ED25519 d’OpenSSH.\'; exit 1; }\n'
            'chroot "$mount_root" /usr/sbin/sshd -t || { printf \'%s\\n\' \'La configuració OpenSSH instal·lada no és vàlida.\'; exit 1; }\n'
            'chroot "$mount_root" systemctl enable ssh.service >/dev/null\n'
            'touch "$mount_root/var/lib/xaac/first-boot.pending" "$mount_root/etc/xaac-first-boot.pending"\n'
            "printf '%s\\n' '[10/10] Verificant la instal·lació...'\n"
            'test -x "$mount_root/usr/bin/systemctl"\n'
            'test -f "$mount_root/etc/fstab"\n'
            'test -f "$mount_root/boot/efi/EFI/BOOT/BOOTX64.EFI"\n'
            'test -s "$mount_root/boot/grub/grub.cfg"\n'
            "test -x \"$mount_root/usr/bin/xaac-thinclient\" || { printf '%s\\n' 'XAAC Thin Client no existeix al sistema instal·lat.'; exit 1; }\n"
            "test -f \"$mount_root/etc/xaac/block5-integration\" || { printf '%s\\n' 'Falta el marcador d’integració del Bloc 5.'; exit 1; }\n"
            "chroot \"$mount_root\" dpkg-query -W -f='${Status} ${Version}\\n' xaac-thinclient | grep -Fq 'install ok installed 1.0.0' || { printf '%s\\n' 'xaac-thinclient 1.0.0 no consta instal·lat.'; exit 1; }\n"
            'grep -Fq "PRETTY_NAME=\\"XAAC Thin Client OS" "$mount_root/etc/os-release" || { printf \'%s\\n\' \'La identitat del sistema instal·lat no és correcta.\'; exit 1; }\n'
            'test ! -e "$mount_root/usr/local/sbin/xaac-installer-welcome" || { printf \'%s\\n\' \'L’instal·lador continua present al sistema instal·lat.\'; exit 1; }\n'
            'test ! -e "$mount_root/etc/systemd/system/multi-user.target.wants/xaac-installer-welcome.service" || { printf \'%s\\n\' \'El servei de l’instal·lador continua habilitat.\'; exit 1; }\n'
            'test -f "$mount_root/var/lib/xaac/installation/consolidated" || { printf \'%s\\n\' \'No existeix el marcador de consolidació.\'; exit 1; }\n'
            '[ "$(cat "$mount_root/etc/hostname")" = "$install_hostname" ] || { printf \'%s\\n\' \'El hostname no ha quedat configurat.\'; exit 1; }\n'
            'grep -Fq "127.0.1.1 $install_hostname" "$mount_root/etc/hosts" || { printf \'%s\\n\' \'/etc/hosts no conté el hostname.\'; exit 1; }\n'
            'grep -Fq "method=auto" "$mount_root/etc/NetworkManager/system-connections/xaac-wired.nmconnection" || { printf \'%s\\n\' \'La xarxa DHCP no ha quedat configurada.\'; exit 1; }\n'
            "final_shadow_password=$(awk -F: '$1 == \"xaac-admin\" {print $2}' \"$mount_root/etc/shadow\")\n"
            '[ "$final_shadow_password" = "$admin_hash" ] || { printf \'%s\\n\' \'La verificació final ha detectat que xaac-admin ha tornat a quedar bloquejat o alterat.\'; exit 1; }\n'
            "admin_hash_fingerprint=$(printf '%s' \"$admin_hash\" | sha256sum | awk '{print $1}')\n"
            "printf 'status=configured\\nscheme=sha512\\nfingerprint=%s\\n' \"$admin_hash_fingerprint\" > \"$mount_root/var/lib/xaac/admin/install-credential-state\"\n"
            'chmod 0640 "$mount_root/var/lib/xaac/admin/install-credential-state"\n'
            'chown root:xaac-admin "$mount_root/var/lib/xaac/admin/install-credential-state"\n'
            'unset admin_password admin_hash final_shadow_password shadow_password\n'
            'cat > "$mount_root/recovery/installer/installation-summary.txt" <<EOF\n'
            'status=completed\n'
            'target=$target\n'
            'root_uuid=$root_uuid\n'
            'efi_uuid=$efi_uuid\n'
            'data_uuid=$data_uuid\n'
            'recovery_uuid=$recovery_uuid\n'
            'bootloader=shim-signed-grub-efi-amd64-removable\n'
            'EOF\n'
            'sync\n'
            "printf '\\n'\n"
            "printf '%s\\n' 'Instal·lació completada i verificada. El disc ja és arrancable en mode UEFI.'\n"
            "printf '%s' 'Premeu Retorn per apagar el sistema: '\n"
            "IFS= read -r _answer\n"
            "systemctl poweroff\n",
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
            "OnFailure=xaac-installer-restore-getty.service\n\n"
            "[Service]\n"
            "Type=idle\n"
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
        self._atomic_write(
            self._inside("/etc/systemd/system/xaac-installer-restore-getty.service"),
            "[Unit]\n"
            "Description=Restore tty1 login after XAAC installer failure\n"
            "After=xaac-installer-welcome.service\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/bin/systemctl start getty@tty1.service\n",
        )

        self._validate_xaac_agent_artifact()
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
                "test \"$(dpkg-query -W -f='${Version}' xaac-agent)\" = '1.0.0-5'; "
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
                "systemctl is-enabled xaac-agent.service >/dev/null; "
                "systemctl is-enabled xaac-privileged-helper.socket >/dev/null",
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
                "systemd-tmpfiles --create /usr/lib/tmpfiles.d/xaac-local-integration.conf; "
                "test -d /var/lib/xaac/thin-client/state; "
                "test -d /var/lib/xaac/thin-client/config; "
                "test -d /run/xaac/thin-client/events; "
                "test -d /run/xaac/commands; "
                "test \"$(stat -c '%U:%G:%a' /var/lib/xaac/thin-client/state)\" = 'xaac-kiosk:xaac-ipc:2750'; "
                "test \"$(stat -c '%U:%G:%a' /var/lib/xaac/thin-client/config)\" = 'xaac-agent:xaac-ipc:2750'; "
                "test \"$(stat -c '%U:%G:%a' /run/xaac/thin-client/events)\" = 'xaac-kiosk:xaac-ipc:2750'; "
                "test \"$(stat -c '%U:%G:%a' /run/xaac/commands)\" = 'xaac-agent:xaac-ipc:2750'; "
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
            self._chroot(["systemctl", "enable", "ssh.service"], phase="configure-ssh")
            self._chroot(["systemctl", "enable", "nftables.service"], phase="configure-firewall")
            self._chroot(["systemctl", "enable", "greetd.service"], phase="configure-greetd")
            self._chroot(["systemctl", "set-default", "graphical.target"], phase="configure-graphical-target")
            self._chroot(["systemctl", "enable", "xaac-installer-welcome.service"], phase="configure-installer-welcome")
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
        params = " ".join(("boot=live", "quiet", *self.settings.kernel_parameters))
        diagnostics = " ".join(("boot=live", "ro", "toram", "xaac.mode=diagnostics", *self.settings.kernel_parameters))
        self._atomic_write(
            self.paths.staging / "boot/grub/grub.cfg",
            "set default=0\nset timeout=5\n\n"
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
        checksum = iso.with_suffix(iso.suffix + ".sha256")
        self._atomic_write(checksum, f"{digest.hexdigest()}  {iso.name}\n")
        self.runner.run(["sha256sum", "-c", checksum.name], phase="verify-sha256", cwd=iso.parent)
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
