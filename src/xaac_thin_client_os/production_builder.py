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
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import yaml

from xaac_thin_client_os.configuration import load_project_configuration
from xaac_thin_client_os.packages import resolve_packages


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
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"$ {rendered}\n")
            log.flush()
            result = subprocess.run(
                list(command),
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        if result.returncode != 0:
            raise ProductionBuildError(
                f"Ha fallat la fase {phase!r} (codi {result.returncode}). "
                f"Consulta {log_path}"
            )


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

    def clean(self) -> None:
        target = self.paths.build_root.resolve(strict=False)
        allowed_parent = (self.paths.project_root / ".build").resolve(strict=False)
        if target.parent != allowed_parent or target.name != "production":
            raise ProductionBuildError(f"Directori de neteja insegur: {target}")
        self.cleanup_chroot_mounts()
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
        self._chroot([
            "apt-get", "install", "--yes", "--no-install-recommends",
            *self.settings.packages,
        ], phase="configure-apt-install")

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
        self._atomic_write(
            self._inside("/etc/xaac/os-release"),
            "NAME=\"XAAC Thin Client OS\"\n"
            f"VERSION=\"{self.settings.version}\"\n"
            "ID=xaac-thin-client-os\n"
            f"VERSION_ID=\"{self.settings.version}\"\n"
            f"XAAC_PROFILE=\"{self.settings.profile}\"\n"
            f"XAAC_BUILD_ID=\"{build_id}\"\n",
        )
        self._atomic_write(
            self._inside("/etc/default/xaac-os"),
            f'XAAC_OS_VERSION="{self.settings.version}"\n'
            f'XAAC_OS_PROFILE="{self.settings.profile}"\n'
            f'XAAC_OS_BUILD_ID="{build_id}"\n',
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
        self._atomic_write(
            self._inside("/etc/systemd/system/getty@tty1.service.d/99-xaac-autologin.conf"),
            "[Service]\nExecStart=\n"
            "ExecStart=-/sbin/agetty --autologin xaac-kiosk --noclear %I $TERM\n",
        )
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
            "printf '%s\\n' '[5/8] Generant la configuració de muntatge...'\n"
            'root_uuid=$(blkid -s UUID -o value "$p2"); efi_uuid=$(blkid -s UUID -o value "$p1"); data_uuid=$(blkid -s UUID -o value "$p3"); recovery_uuid=$(blkid -s UUID -o value "$p4")\n'
            '[ -n "$root_uuid" ] && [ -n "$efi_uuid" ] && [ -n "$data_uuid" ] && [ -n "$recovery_uuid" ] || { printf \'%s\\n\' \'No s’han pogut obtindre tots els UUID.\'; exit 1; }\n'
            'cat > "$mount_root/etc/fstab" <<EOF\n'
            'UUID=$root_uuid / ext4 defaults,noatime 0 1\n'
            'UUID=$efi_uuid /boot/efi vfat umask=0077 0 1\n'
            'UUID=$data_uuid /data ext4 defaults,noatime 0 2\n'
            'UUID=$recovery_uuid /recovery ext4 defaults,noatime 0 2\n'
            'EOF\n'
            "printf '%s\\n' '[6/8] Instal·lant GRUB UEFI...'\n"
            'mkdir -p "$mount_root/dev" "$mount_root/proc" "$mount_root/sys" "$mount_root/run"\n'
            'mount --rbind /dev "$mount_root/dev"; mount --make-rslave "$mount_root/dev"\n'
            'mount -t proc proc "$mount_root/proc"\n'
            'mount --rbind /sys "$mount_root/sys"; mount --make-rslave "$mount_root/sys"\n'
            'mount --rbind /run "$mount_root/run"; mount --make-rslave "$mount_root/run"\n'
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
            'for efi_file in "$mount_root/boot/efi/EFI/BOOT/BOOTX64.EFI" "$mount_root/boot/efi/EFI/BOOT/grubx64.efi"; do [ -s "$efi_file" ] || { printf \'No existeix o està buit: %s\\n\' "$efi_file"; exit 1; }; [ "$(od -An -tx1 -N2 "$efi_file" | tr -d \' \\n\')" = 4d5a ] || { printf \'No és un executable PE/COFF vàlid: %s\\n\' "$efi_file"; exit 1; }; done\n'
            'grep -Fq "$root_uuid" "$mount_root/boot/efi/EFI/BOOT/grub.cfg" || { printf \'%s\\n\' \'El fallback GRUB no referencia l’UUID arrel.\'; exit 1; }\n'
            'sgdisk -i 1 "$target" | grep -Eqi \'EF00|EFI system partition\' || { printf \'%s\\n\' \'La primera partició no és una ESP GPT vàlida.\'; exit 1; }\n'
            'sync; umount "$mount_root/boot/efi"\n'
            'fsck.vfat -n "$p1" >/dev/null || { printf \'%s\\n\' \'La partició EFI FAT32 no supera la verificació.\'; exit 1; }\n'
            'mount "$p1" "$mount_root/boot/efi"\n'
            "printf '%s\\n' '[7/9] Configurant l’administrador local...'\n"
            'printf \'%s:%s\\n\' xaac-admin "$admin_password" | chroot "$mount_root" chpasswd\n'
            'chroot "$mount_root" usermod --unlock --shell /bin/bash xaac-admin\n'
            'chroot "$mount_root" chage -E -1 -I -1 -m 0 xaac-admin\n'
            'passwd_status=$(chroot "$mount_root" passwd -S xaac-admin 2>/dev/null | awk \'{print $2}\')\n'
            'shadow_password=$(chroot "$mount_root" getent shadow xaac-admin 2>/dev/null | cut -d: -f2)\n'
            'admin_shell=$(chroot "$mount_root" getent passwd xaac-admin 2>/dev/null | cut -d: -f7)\n'
            '[ "$passwd_status" = P ] || { printf \'%s\\n\' \'No s’ha pogut activar la contrasenya de xaac-admin.\'; exit 1; }\n'
            'case "$shadow_password" in \'\'|\\!*|\\**) printf \'%s\\n\' \'El compte xaac-admin continua bloquejat en /etc/shadow.\'; exit 1 ;; esac\n'
            '[ "$admin_shell" = /bin/bash ] || { printf \'%s\\n\' \'La shell de xaac-admin no és interactiva.\'; exit 1; }\n'
            'chroot "$mount_root" mkdir -p /var/lib/xaac/admin\n'
            'chroot "$mount_root" install -o root -g xaac-admin -m 0640 /dev/null /var/lib/xaac/admin/password-changed\n'
            'unset admin_password\n'
            "printf '%s\\n' '[8/9] Preparant el primer arrencament...'\n"
            ': > "$mount_root/etc/machine-id"\n'
            'rm -f "$mount_root/var/lib/dbus/machine-id" "$mount_root"/etc/ssh/ssh_host_* "$mount_root/var/lib/systemd/random-seed"\n'
            'mkdir -p "$mount_root/var/lib/xaac" "$mount_root/recovery/installer"\n'
            'touch "$mount_root/var/lib/xaac/first-boot.pending" "$mount_root/etc/xaac-first-boot.pending"\n'
            'rm -f "$mount_root/etc/systemd/system/multi-user.target.wants/xaac-installer-welcome.service"\n'
            "printf '%s\\n' '[9/9] Verificant la instal·lació...'\n"
            'test -x "$mount_root/usr/bin/systemctl"\n'
            'test -f "$mount_root/etc/fstab"\n'
            'test -f "$mount_root/boot/efi/EFI/BOOT/BOOTX64.EFI"\n'
            'test -s "$mount_root/boot/grub/grub.cfg"\n'
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

        debs = self._copy_valid_debs()
        with self._chroot_mounts():
            self._install_runtime_packages()
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
                "--create-home --shell /bin/bash --gid xaac-kiosk xaac-kiosk",
            ], phase="configure-user-kiosk")
            # The kiosk account is an autologin session account, so it must have
            # a valid login shell. Enforce it even on incremental builds where
            # the account may already exist from an earlier rootfs.
            self._chroot(["usermod", "--shell", "/bin/bash", "xaac-kiosk"], phase="configure-shell-kiosk")
            self._chroot(["passwd", "--lock", "xaac-admin"], phase="configure-lock-admin")
            self._chroot(["passwd", "--lock", "xaac-kiosk"], phase="configure-lock-kiosk")
            if debs:
                self._chroot(["apt-get", "install", "--yes", *debs], phase="configure-xaac-packages")
            self._chroot(["systemctl", "enable", "NetworkManager.service"], phase="configure-networkmanager")
            self._chroot(["systemctl", "enable", "ssh.service"], phase="configure-ssh")
            self._chroot(["systemctl", "enable", "nftables.service"], phase="configure-firewall")
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
        output = self.paths.build_root / "rootfs.squashfs"
        output.unlink(missing_ok=True)
        self.runner.run([
            "mksquashfs", str(self.paths.rootfs), str(output),
            "-comp", "xz", "-b", "1M", "-noappend", "-no-progress",
            "-e", "boot",
        ], phase="squashfs")
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
