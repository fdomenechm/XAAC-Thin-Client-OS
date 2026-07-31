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
    live_username: str
    live_user_fullname: str

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
            "live-config",
            "sudo",
            "dbus",
            "network-manager",
            "python3",
            "python3-venv",
            "grub-pc-bin",
            "grub-efi-amd64-bin",
            "gdisk",
            "dosfstools",
            "e2fsprogs",
            "parted",
            "squashfs-tools",
        }
        packages = tuple(sorted(set(resolved.packages).union(mandatory)))
        kernel_parameters: list[str] = []
        for profile_name in resolved.profile_chain:
            profile_raw = yaml_mapping(f"profiles/{profile_name}/profile.yaml")
            values = profile_raw.get("kernel_parameters", [])
            if isinstance(values, list):
                kernel_parameters.extend(str(value) for value in values if value)

        fallback = localization.get("fallback_locales", [])
        live = iso.get("live", {})
        if not isinstance(live, dict):
            raise ProductionBuildError("config/iso-builder.yaml: live ha de ser un mapa")
        live_username = str(live.get("username", "xaac-kiosk")).strip()
        if not live_username or not live_username.replace("-", "").replace("_", "").isalnum():
            raise ProductionBuildError("Nom d'usuari live invàlid")
        live_user_fullname = str(live.get("user_fullname", "XAAC Kiosk")).strip() or "XAAC Kiosk"
        if any(char in live_user_fullname for char in "\n\r\t\"'" ):
            raise ProductionBuildError("Nom complet de l'usuari live invàlid")
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
            live_username=live_username,
            live_user_fullname=live_user_fullname,
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

    def clean(self) -> None:
        target = self.paths.build_root.resolve(strict=False)
        allowed_parent = (self.paths.project_root / ".build").resolve(strict=False)
        if target.parent != allowed_parent or target.name != "production":
            raise ProductionBuildError(f"Directori de neteja insegur: {target}")
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
            ("/dev", "--rbind"),
            ("/proc", "-t proc"),
            ("/sys", "--rbind"),
            ("/run", "--rbind"),
        )
        mounted: list[Path] = []
        try:
            for source, mode in mounts:
                target = self._inside(source)
                target.mkdir(parents=True, exist_ok=True)
                if source == "/proc":
                    command = ["mount", "-t", "proc", "proc", str(target)]
                else:
                    command = ["mount", "--rbind", source, str(target)]
                self.runner.run(command, phase=f"mount-{source.strip('/').replace('/', '-') or 'root'}")
                mounted.append(target)
            yield
        finally:
            for target in reversed(mounted):
                subprocess.run(["umount", "-R", "-l", str(target)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
        self._atomic_write(
            self._inside("/etc/systemd/system/getty@tty1.service.d/autologin.conf"),
            "[Service]\nExecCondition=/bin/sh -c '! grep -qw xaac.mode=installer /proc/cmdline'\nExecStart=\nExecStart=-/sbin/agetty --autologin xaac-kiosk --noclear %I $TERM\n",
        )

        installer_source = self.paths.project_root / "builder/scripts/xaac-installer"
        if not installer_source.is_file():
            raise ProductionBuildError(f"Falta l'instal·lador de producció: {installer_source}")
        installer_target = self._inside("/usr/local/sbin/xaac-installer")
        installer_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(installer_source, installer_target)
        os.chmod(installer_target, 0o750)
        self._atomic_write(
            self._inside("/etc/systemd/system/xaac-installer.service"),
            "[Unit]\nDescription=Instal·lador de XAAC Thin Client OS\n"
            "ConditionKernelCommandLine=xaac.mode=installer\n"
            "After=local-fs.target systemd-udev-settle.service\n"
            "Before=getty@tty1.service\nConflicts=getty@tty1.service\n\n"
            "[Service]\nType=oneshot\nStandardInput=tty-force\nStandardOutput=tty\nStandardError=tty\n"
            "TTYPath=/dev/tty1\nTTYReset=yes\nTTYVHangup=yes\n"
            "ExecStart=/usr/local/sbin/xaac-installer\nRemainAfterExit=yes\n\n"
            "[Install]\nWantedBy=multi-user.target\n",
        )
        wants = self._inside("/etc/systemd/system/multi-user.target.wants")
        wants.mkdir(parents=True, exist_ok=True)
        link = wants / "xaac-installer.service"
        link.unlink(missing_ok=True)
        link.symlink_to("../xaac-installer.service")

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
        staged_squashfs = self.paths.staging / "live/filesystem.squashfs"
        shutil.copy2(squashfs, staged_squashfs)
        digest = hashlib.sha256(staged_squashfs.read_bytes()).hexdigest()
        self._atomic_write(
            self.paths.staging / "live/filesystem.squashfs.sha256",
            f"{digest}  filesystem.squashfs\n",
        )
        live_identity = (
            f"username={self.settings.live_username}",
            f"user-fullname={self.settings.live_user_fullname.replace(' ', '_')}",
        )
        params = " ".join(("boot=live", "components", *live_identity, "quiet", *self.settings.kernel_parameters))
        diagnostics = " ".join(("boot=live", "components", *live_identity, "ro", "toram", "xaac.mode=diagnostics", *self.settings.kernel_parameters))
        self._atomic_write(
            self.paths.staging / "boot/grub/grub.cfg",
            "set default=0\nset timeout=5\n\n"
            "menuentry 'Install XAAC Thin Client OS' {\n"
            f"  linux /live/vmlinuz {params} xaac.mode=installer\n"
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
        "--phase", action="append", choices=ProductionIsoBuilder.PHASES,
        help="Executa només aquesta fase; es pot repetir",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        builder = ProductionIsoBuilder(args.root, dry_run=args.dry_run)
        if args.clean:
            builder.clean()
        phases = tuple(args.phase) if args.phase else ProductionIsoBuilder.PHASES
        iso = builder.run(phases)
        if not args.dry_run and "verify" in phases:
            print(f"ISO generada correctament: {iso}")
        return 0
    except (ProductionBuildError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            root = BuildPaths.create(args.root)
            _restore_owner(root.project_root / ".build")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
