"""Deterministic package installation inside a Debian root filesystem."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


class PackageInstallationError(RuntimeError):
    """Raised when packages cannot be installed safely in the root filesystem."""


@dataclass(frozen=True, slots=True)
class PackageInstallationPlan:
    """Immutable package installation plan for one build workspace."""

    rootfs: Path
    packages: tuple[str, ...]
    excluded: tuple[str, ...]

    def update_command(self) -> tuple[str, ...]:
        """Return the APT index refresh command executed through chroot."""
        return ("chroot", str(self.rootfs), "apt-get", "update")

    def install_command(self) -> tuple[str, ...]:
        """Return the deterministic minimal package installation command."""
        return (
            "chroot",
            str(self.rootfs),
            "apt-get",
            "install",
            "--yes",
            "--no-install-recommends",
            "--no-install-suggests",
            *self.packages,
        )

    def to_manifest(self) -> dict[str, object]:
        """Return a stable JSON-compatible representation of the plan."""
        return {
            "packages": list(self.packages),
            "package_count": len(self.packages),
            "excluded": list(self.excluded),
            "update_command": list(self.update_command()),
            "install_command": list(self.install_command()),
            "noninteractive": True,
            "install_recommends": False,
            "install_suggests": False,
        }


@dataclass(frozen=True, slots=True)
class PackageInstallationResult:
    """Outcome and log produced by a package installation run."""

    plan: PackageInstallationPlan
    log_path: Path
    executed: bool
    commands_executed: int


def create_package_installation_plan(
    rootfs: Path,
    packages: Sequence[str],
    excluded: Sequence[str] = (),
) -> PackageInstallationPlan:
    """Validate and normalize a deterministic package installation plan."""
    resolved = rootfs.resolve()
    if resolved == Path("/") or resolved.parent == Path("/"):
        raise PackageInstallationError(f"Rootfs insegur: {resolved}")

    normalized_packages = tuple(sorted(set(packages)))
    normalized_excluded = tuple(sorted(set(excluded)))
    if not normalized_packages:
        raise PackageInstallationError("La llista efectiva de paquets està buida")
    overlap = sorted(set(normalized_packages).intersection(normalized_excluded))
    if overlap:
        raise PackageInstallationError(
            "Hi ha paquets simultàniament inclosos i exclosos: " + ", ".join(overlap)
        )
    for package in (*normalized_packages, *normalized_excluded):
        if (
            not package
            or any(character.isspace() for character in package)
            or package.startswith("-")
        ):
            raise PackageInstallationError(f"Nom de paquet no vàlid: {package!r}")

    return PackageInstallationPlan(resolved, normalized_packages, normalized_excluded)


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class PackageInstaller:
    """Run APT inside a validated rootfs with reproducible noninteractive settings."""

    def __init__(
        self,
        *,
        geteuid: Callable[[], int] = os.geteuid,
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self._geteuid = geteuid
        self._runner = runner

    @staticmethod
    def _validate_rootfs(plan: PackageInstallationPlan) -> None:
        required = (
            plan.rootfs / "etc" / "debian_version",
            plan.rootfs / "usr" / "bin" / "apt-get",
            plan.rootfs / "etc" / "apt" / "sources.list.d" / "xaac.sources",
            plan.rootfs / "etc" / "apt" / "apt.conf.d" / "99xaac-minimal",
        )
        missing = tuple(path for path in required if not path.is_file())
        if missing:
            rendered = ", ".join(str(path) for path in missing)
            raise PackageInstallationError(
                f"El rootfs no està preparat per instal·lar paquets; falten: {rendered}"
            )

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "DEBIAN_FRONTEND": "noninteractive",
                "DEBCONF_NONINTERACTIVE_SEEN": "true",
                "LC_ALL": "C.UTF-8",
                "LANG": "C.UTF-8",
            }
        )
        return environment

    def execute(
        self,
        plan: PackageInstallationPlan,
        log_path: Path,
        *,
        dry_run: bool = False,
    ) -> PackageInstallationResult:
        """Refresh APT indexes and install all packages, or only record the plan."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        commands = (plan.update_command(), plan.install_command())
        if dry_run:
            log_path.write_text(
                "DRY-RUN\n" + "\n".join(" ".join(command) for command in commands) + "\n",
                encoding="utf-8",
            )
            return PackageInstallationResult(plan, log_path, False, 0)

        if self._geteuid() != 0:
            raise PackageInstallationError(
                "La instal·lació de paquets requereix privilegis de root"
            )
        self._validate_rootfs(plan)

        environment = self._environment()
        with log_path.open("w", encoding="utf-8") as log_file:
            for command in commands:
                log_file.write(f"$ {' '.join(command)}\n")
                log_file.flush()
                try:
                    self._runner(
                        command,
                        check=True,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        text=True,
                        env=environment,
                    )
                except subprocess.CalledProcessError as exc:
                    raise PackageInstallationError(
                        f"Ha fallat la instal·lació de paquets amb codi {exc.returncode}; "
                        f"consulteu {log_path}"
                    ) from exc
                except OSError as exc:
                    raise PackageInstallationError(
                        f"No s'ha pogut executar {command[0]!r}: {exc}"
                    ) from exc

        return PackageInstallationResult(plan, log_path, True, len(commands))
