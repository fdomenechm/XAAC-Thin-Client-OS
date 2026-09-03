"""Deterministic package resolution for XAAC Thin Client OS builds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xaac_thin_client_os.configuration import (
    ConfigurationValidationError,
    HardwareProfile,
    ProjectConfiguration,
    load_yaml,
)


@dataclass(frozen=True, slots=True)
class ResolvedPackages:
    """Effective packages, exclusions and profile inheritance metadata."""

    packages: tuple[str, ...]
    excluded: tuple[str, ...]
    profile_chain: tuple[str, ...]
    sources: tuple[tuple[str, tuple[str, ...]], ...]

    def to_manifest(self) -> dict[str, object]:
        """Return a stable JSON-serialisable package manifest."""
        return {
            "profile_chain": list(self.profile_chain),
            "packages": list(self.packages),
            "excluded": list(self.excluded),
            "package_count": len(self.packages),
            "sources": {name: list(values) for name, values in self.sources},
        }


def _load_profile(root: Path, name: str) -> HardwareProfile:
    path = root / "profiles" / name / "profile.yaml"
    if not path.is_file():
        raise ConfigurationValidationError(
            f"El perfil heretat {name!r} no existeix en {path.relative_to(root)}"
        )
    profile = HardwareProfile.from_mapping(load_yaml(path))
    if profile.name != name:
        raise ConfigurationValidationError(
            f"profile.name={profile.name!r} no coincideix amb el directori {name!r}"
        )
    overlap = sorted(set(profile.packages).intersection(profile.exclude_packages))
    if overlap:
        raise ConfigurationValidationError(
            f"El perfil {name!r} inclou i exclou els mateixos paquets: {', '.join(overlap)}"
        )
    return profile


def load_profile_chain(root: Path, selected: HardwareProfile) -> tuple[HardwareProfile, ...]:
    """Load profile inheritance from the oldest ancestor to the selected profile."""
    root = root.resolve()
    chain: list[HardwareProfile] = []
    visiting: list[str] = []

    def visit(profile: HardwareProfile) -> None:
        if profile.name in visiting:
            cycle = " -> ".join((*visiting, profile.name))
            raise ConfigurationValidationError(f"Cicle d'herència de perfils detectat: {cycle}")
        if any(existing.name == profile.name for existing in chain):
            return
        visiting.append(profile.name)
        if profile.extends is not None:
            visit(_load_profile(root, profile.extends))
        visiting.pop()
        chain.append(profile)

    overlap = sorted(set(selected.packages).intersection(selected.exclude_packages))
    if overlap:
        raise ConfigurationValidationError(
            f"El perfil {selected.name!r} inclou i exclou els mateixos paquets: "
            f"{', '.join(overlap)}"
        )
    visit(selected)
    return tuple(chain)


def resolve_packages(root: Path, configuration: ProjectConfiguration) -> ResolvedPackages:
    """Resolve package groups and inherited profiles into a stable effective list."""
    profile_chain = load_profile_chain(root, configuration.profile)
    groups: list[tuple[str, tuple[str, ...]]] = [
        ("base", configuration.packages.base),
        ("graphical", configuration.packages.graphical),
        ("xaac", configuration.packages.xaac),
        ("optional", configuration.packages.optional),
    ]
    groups.extend((f"profile:{profile.name}", profile.packages) for profile in profile_chain)

    excluded = set(configuration.packages.exclude)
    for profile in profile_chain:
        excluded.update(profile.exclude_packages)

    selected: set[str] = set()
    source_map: list[tuple[str, tuple[str, ...]]] = []
    for source, values in groups:
        accepted = tuple(sorted(set(values) - excluded))
        source_map.append((source, accepted))
        selected.update(accepted)

    return ResolvedPackages(
        packages=tuple(sorted(selected)),
        excluded=tuple(sorted(excluded)),
        profile_chain=tuple(profile.name for profile in profile_chain),
        sources=tuple(source_map),
    )
