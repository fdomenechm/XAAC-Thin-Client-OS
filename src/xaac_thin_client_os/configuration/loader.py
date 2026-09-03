"""Safe YAML loading and cross-file validation for builder configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from xaac_thin_client_os.configuration.errors import (
    ConfigurationFileError,
    ConfigurationValidationError,
)
from xaac_thin_client_os.configuration.model import (
    BuildConfig,
    HardwareProfile,
    PackageConfig,
    RepositoryConfig,
)
from xaac_thin_client_os.metadata import PROJECT_NAME, __version__


@dataclass(frozen=True, slots=True)
class ProjectConfiguration:
    """Validated configuration assembled from all phase 1.2 files."""

    build: BuildConfig
    packages: PackageConfig
    repositories: tuple[RepositoryConfig, ...]
    profile: HardwareProfile


def load_yaml(path: Path) -> Any:
    """Load one YAML document using the safe parser."""
    try:
        with path.open("r", encoding="utf-8") as stream:
            return yaml.safe_load(stream)
    except OSError as exc:
        raise ConfigurationFileError(f"No s'ha pogut llegir {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationFileError(f"YAML invàlid en {path}: {exc}") from exc


def load_repositories(raw: object) -> tuple[RepositoryConfig, ...]:
    """Validate the repository document."""
    if not isinstance(raw, dict) or set(raw) != {"repositories"}:
        raise ConfigurationValidationError(
            "repositories.yaml ha de contindre únicament la clau repositories"
        )
    entries = raw["repositories"]
    if not isinstance(entries, list) or not entries:
        raise ConfigurationValidationError("repositories ha de ser una llista no buida")
    repositories = tuple(
        RepositoryConfig.from_mapping(entry, index) for index, entry in enumerate(entries)
    )
    names = [repository.name for repository in repositories]
    if len(names) != len(set(names)):
        raise ConfigurationValidationError("repositories conté noms duplicats")
    return repositories


def load_project_configuration(root: Path) -> ProjectConfiguration:
    """Load and cross-validate the complete project configuration tree."""
    root = root.resolve()
    build = BuildConfig.from_mapping(load_yaml(root / "config" / "build.yaml"))
    packages = PackageConfig.from_mapping(load_yaml(root / "config" / "packages.yaml"))
    repositories = load_repositories(load_yaml(root / "config" / "repositories.yaml"))
    profile_path = root / "profiles" / build.profile / "profile.yaml"
    profile = HardwareProfile.from_mapping(load_yaml(profile_path))

    if build.project != PROJECT_NAME:
        raise ConfigurationValidationError(
            f"build.project ha de ser {PROJECT_NAME!r}, no {build.project!r}"
        )
    if build.version != __version__:
        raise ConfigurationValidationError(
            f"build.version={build.version} no coincideix amb VERSION={__version__}"
        )
    if build.architecture != profile.architecture:
        raise ConfigurationValidationError(
            "L'arquitectura de build.yaml no coincideix amb la del perfil"
        )
    if profile.name != build.profile:
        raise ConfigurationValidationError(
            f"profile.name={profile.name!r} no coincideix amb build.profile={build.profile!r}"
        )
    if build.image.size_mib > profile.storage_mib:
        raise ConfigurationValidationError(
            "La mida de la imatge supera l'emmagatzematge declarat pel perfil"
        )
    return ProjectConfiguration(
        build=build,
        packages=packages,
        repositories=repositories,
        profile=profile,
    )
