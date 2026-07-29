"""Debian 13 minimal root filesystem bootstrap support."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from xaac_thin_client_os.configuration import BuildConfig


class BootstrapError(RuntimeError):
    """Raised when the Debian bootstrap cannot be planned or executed."""


@dataclass(frozen=True, slots=True)
class BootstrapPlan:
    """Immutable, auditable debootstrap execution plan."""

    executable: Path
    suite: str
    target: Path
    mirror: str
    architecture: str
    components: tuple[str, ...]
    variant: str = "minbase"

    def command(self) -> tuple[str, ...]:
        """Return the exact command used to create the Debian root filesystem."""
        return (
            str(self.executable),
            f"--arch={self.architecture}",
            f"--variant={self.variant}",
            f"--components={','.join(self.components)}",
            self.suite,
            str(self.target),
            self.mirror,
        )

    def to_manifest(self) -> dict[str, object]:
        """Return a JSON-compatible representation for logs and manifests."""
        return {
            "tool": str(self.executable),
            "suite": self.suite,
            "target": str(self.target),
            "mirror": self.mirror,
            "architecture": self.architecture,
            "components": list(self.components),
            "variant": self.variant,
            "command": list(self.command()),
        }


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Outcome of a bootstrap execution or dry run."""

    plan: BootstrapPlan
    log_path: Path
    executed: bool


def find_debootstrap(*, search: Callable[[str], str | None] = shutil.which) -> Path:
    """Locate debootstrap in PATH and reject an unavailable tool."""
    value = search("debootstrap")
    if not value:
        raise BootstrapError(
            "No s'ha trobat debootstrap; instal·leu-lo amb 'apt install debootstrap'"
        )
    path = Path(value)
    if not path.is_absolute():
        raise BootstrapError("La ruta de debootstrap ha de ser absoluta")
    return path


def create_bootstrap_plan(
    build: BuildConfig,
    target: Path,
    *,
    executable: Path | None = None,
) -> BootstrapPlan:
    """Create a validated Debian bootstrap plan for one isolated workspace."""
    resolved_target = target.resolve()
    if resolved_target == Path("/") or resolved_target.parent == Path("/"):
        raise BootstrapError(f"Destinació de bootstrap insegura: {resolved_target}")
    if resolved_target.exists() and any(resolved_target.iterdir()):
        raise BootstrapError(f"La destinació de bootstrap no està buida: {resolved_target}")
    return BootstrapPlan(
        executable=(executable or find_debootstrap()).resolve(),
        suite=build.debian.suite,
        target=resolved_target,
        mirror=build.debian.mirror,
        architecture=build.architecture.value,
        components=build.debian.components,
    )


class BootstrapRunner:
    """Execute a bootstrap plan with deterministic logging and cleanup."""

    def __init__(
        self,
        *,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        geteuid: Callable[[], int] = os.geteuid,
    ) -> None:
        self._run = run
        self._geteuid = geteuid

    def execute(
        self,
        plan: BootstrapPlan,
        log_path: Path,
        *,
        dry_run: bool = False,
        keep_partial: bool = False,
    ) -> BootstrapResult:
        """Execute debootstrap or record its exact command in dry-run mode."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = plan.command()
        if dry_run:
            log_path.write_text("DRY-RUN\n" + " ".join(command) + "\n", encoding="utf-8")
            return BootstrapResult(plan=plan, log_path=log_path, executed=False)
        if self._geteuid() != 0:
            raise BootstrapError("El bootstrap de Debian requereix privilegis de root")
        plan.target.mkdir(parents=True, mode=0o750, exist_ok=True)
        try:
            completed = self._run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                env={
                    "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
                    "LC_ALL": "C",
                },
            )
        except OSError as exc:
            raise BootstrapError(f"No s'ha pogut executar debootstrap: {exc}") from exc
        output = (
            f"COMMAND: {' '.join(command)}\n"
            f"RETURN_CODE: {completed.returncode}\n"
            "--- STDOUT ---\n"
            f"{completed.stdout}"
            "\n--- STDERR ---\n"
            f"{completed.stderr}"
        )
        log_path.write_text(output, encoding="utf-8")
        if completed.returncode != 0:
            if not keep_partial and plan.target.exists():
                shutil.rmtree(plan.target)
            raise BootstrapError(
                f"debootstrap ha fallat amb codi {completed.returncode}; consulteu {log_path}"
            )
        if not (plan.target / "etc" / "debian_version").is_file():
            if not keep_partial and plan.target.exists():
                shutil.rmtree(plan.target)
            raise BootstrapError("debootstrap ha finalitzat sense crear /etc/debian_version")
        return BootstrapResult(plan=plan, log_path=log_path, executed=True)
