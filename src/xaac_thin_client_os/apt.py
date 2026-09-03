"""Secure and deterministic APT configuration for a Debian root filesystem."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from xaac_thin_client_os.configuration import RepositoryConfig


class AptConfigurationError(RuntimeError):
    """Raised when APT configuration cannot be planned or applied safely."""


@dataclass(frozen=True, slots=True)
class AptConfigurationPlan:
    """Immutable APT configuration plan for one Debian root filesystem."""

    rootfs: Path
    repositories: tuple[RepositoryConfig, ...]
    architecture: str

    @property
    def sources_path(self) -> Path:
        return self.rootfs / "etc" / "apt" / "sources.list.d" / "xaac.sources"

    @property
    def policy_path(self) -> Path:
        return self.rootfs / "etc" / "apt" / "apt.conf.d" / "99xaac-minimal"

    @property
    def legacy_sources_path(self) -> Path:
        return self.rootfs / "etc" / "apt" / "sources.list"

    def render_sources(self) -> str:
        """Render enabled repositories in deterministic Deb822 format."""
        blocks: list[str] = []
        for repository in sorted(self.repositories, key=lambda item: item.name):
            if not repository.enabled:
                continue
            blocks.append(
                "\n".join(
                    (
                        "Types: deb",
                        f"URIs: {repository.uri}",
                        f"Suites: {' '.join(repository.suites)}",
                        f"Components: {' '.join(repository.components)}",
                        f"Architectures: {self.architecture}",
                        f"Signed-By: {repository.signed_by}",
                    )
                )
            )
        if not blocks:
            raise AptConfigurationError("No hi ha cap repositori APT habilitat")
        return "\n\n".join(blocks) + "\n"

    @staticmethod
    def render_policy() -> str:
        """Render the low-footprint package installation policy."""
        return (
            'APT::Install-Recommends "false";\n'
            'APT::Install-Suggests "false";\n'
            'Acquire::Languages "none";\n'
            'Acquire::Retries "3";\n'
            'Dpkg::Use-Pty "0";\n'
        )

    def to_manifest(self) -> dict[str, object]:
        """Return a JSON-compatible description of the effective APT plan."""
        enabled = tuple(item for item in self.repositories if item.enabled)
        return {
            "format": "deb822",
            "architecture": self.architecture,
            "sources_path": str(self.sources_path),
            "policy_path": str(self.policy_path),
            "repositories": [
                {
                    "name": item.name,
                    "uri": item.uri,
                    "suites": list(item.suites),
                    "components": list(item.components),
                    "signed_by": str(item.signed_by),
                }
                for item in sorted(enabled, key=lambda repository: repository.name)
            ],
            "install_recommends": False,
            "install_suggests": False,
        }


@dataclass(frozen=True, slots=True)
class AptConfigurationResult:
    """Files produced by an APT configuration run."""

    plan: AptConfigurationPlan
    files: tuple[Path, ...]
    log_path: Path
    executed: bool


def create_apt_configuration_plan(
    rootfs: Path,
    repositories: Iterable[RepositoryConfig],
    architecture: str,
) -> AptConfigurationPlan:
    """Validate paths and create a deterministic APT configuration plan."""
    resolved = rootfs.resolve()
    if resolved == Path("/") or resolved.parent == Path("/"):
        raise AptConfigurationError(f"Rootfs insegur: {resolved}")
    plan = AptConfigurationPlan(resolved, tuple(repositories), architecture)
    plan.render_sources()
    return plan


class AptConfigurator:
    """Apply an APT plan atomically and without following unsafe symlinks."""

    def __init__(self, *, geteuid: Callable[[], int] = os.geteuid) -> None:
        self._geteuid = geteuid

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise AptConfigurationError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o644)
        temporary.replace(path)

    @staticmethod
    def _validate_rootfs(plan: AptConfigurationPlan) -> None:
        if not (plan.rootfs / "etc" / "debian_version").is_file():
            raise AptConfigurationError("El directori actual no conté un rootfs Debian vàlid")
        for repository in plan.repositories:
            if not repository.enabled:
                continue
            keyring = plan.rootfs / repository.signed_by.relative_to("/")
            if not keyring.is_file():
                raise AptConfigurationError(
                    f"No existeix el keyring requerit dins del rootfs: {repository.signed_by}"
                )

    def execute(
        self,
        plan: AptConfigurationPlan,
        log_path: Path,
        *,
        dry_run: bool = False,
    ) -> AptConfigurationResult:
        """Write APT sources and policy, or only record the plan in dry-run mode."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        sources = plan.render_sources()
        policy = plan.render_policy()
        if dry_run:
            log_path.write_text(
                "DRY-RUN\n--- xaac.sources ---\n" + sources + "--- 99xaac-minimal ---\n" + policy,
                encoding="utf-8",
            )
            return AptConfigurationResult(plan, (), log_path, False)
        if self._geteuid() != 0:
            raise AptConfigurationError(
                "La configuració APT del rootfs requereix privilegis de root"
            )
        self._validate_rootfs(plan)
        self._write_atomic(plan.sources_path, sources)
        self._write_atomic(plan.policy_path, policy)
        self._write_atomic(
            plan.legacy_sources_path,
            "# Gestionat per XAAC Thin Client OS. Consulteu sources.list.d/xaac.sources\n",
        )
        files = (plan.sources_path, plan.policy_path, plan.legacy_sources_path)
        log_path.write_text(
            "APT CONFIGURED\n" + "\n".join(str(path) for path in files) + "\n",
            encoding="utf-8",
        )
        return AptConfigurationResult(plan, files, log_path, True)
