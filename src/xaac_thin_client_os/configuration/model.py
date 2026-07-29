"""Typed configuration model for the XAAC Thin Client OS image builder."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from xaac_thin_client_os.configuration.errors import ConfigurationValidationError


class Architecture(StrEnum):
    """Architectures supported by the initial builder model."""

    AMD64 = "amd64"


class ReleaseChannel(StrEnum):
    """Publication channels accepted by XAAC Thin Client OS."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    CANDIDATE = "candidate"
    STABLE = "stable"
    LONG_TERM = "long-term"


class ImageFormat(StrEnum):
    """Output formats planned by the image builder."""

    ISO = "iso"
    IMG = "img"
    RECOVERY = "recovery-img"
    PXE = "pxe"


def _mapping(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationValidationError(f"{location} ha de ser un mapa")
    if not all(isinstance(key, str) for key in value):
        raise ConfigurationValidationError(f"{location} només pot contindre claus de text")
    return value


def _required_text(data: dict[str, Any], key: str, location: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationValidationError(f"{location}.{key} ha de ser text no buit")
    return value.strip()


def _optional_text(data: dict[str, Any], key: str, location: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationValidationError(f"{location}.{key} ha de ser text no buit")
    return value.strip()


def _positive_int(data: dict[str, Any], key: str, location: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigurationValidationError(f"{location}.{key} ha de ser un enter positiu")
    return value


def _enum(enum_type: type[StrEnum], raw: object, location: str) -> StrEnum:
    if not isinstance(raw, str):
        raise ConfigurationValidationError(f"{location} ha de ser text")
    try:
        return enum_type(raw)
    except ValueError as exc:
        accepted = ", ".join(item.value for item in enum_type)
        raise ConfigurationValidationError(
            f"{location} té el valor desconegut {raw!r}; valors admesos: {accepted}"
        ) from exc


def _text_tuple(raw: object, location: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if raw is None and allow_empty:
        return ()
    if not isinstance(raw, list):
        raise ConfigurationValidationError(f"{location} ha de ser una llista")
    values: list[str] = []
    for index, value in enumerate(raw):
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationValidationError(f"{location}[{index}] ha de ser text no buit")
        normalized = value.strip()
        if normalized in values:
            raise ConfigurationValidationError(f"{location} conté el duplicat {normalized!r}")
        values.append(normalized)
    if not allow_empty and not values:
        raise ConfigurationValidationError(f"{location} no pot estar buida")
    return tuple(values)


def _reject_unknown(data: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigurationValidationError(
            f"{location} conté camps desconeguts: {', '.join(unknown)}"
        )


@dataclass(frozen=True, slots=True)
class DebianConfig:
    """Debian base release and mirror selection."""

    suite: str
    mirror: str
    components: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: object) -> Self:
        data = _mapping(raw, "build.debian")
        _reject_unknown(data, {"suite", "mirror", "components"}, "build.debian")
        mirror = _required_text(data, "mirror", "build.debian")
        if not mirror.startswith("https://"):
            raise ConfigurationValidationError("build.debian.mirror ha d'utilitzar HTTPS")
        return cls(
            suite=_required_text(data, "suite", "build.debian"),
            mirror=mirror.rstrip("/"),
            components=_text_tuple(
                data.get("components"), "build.debian.components", allow_empty=False
            ),
        )


@dataclass(frozen=True, slots=True)
class ImageConfig:
    """Image output parameters."""

    formats: tuple[ImageFormat, ...]
    size_mib: int
    output_directory: Path

    @classmethod
    def from_mapping(cls, raw: object) -> Self:
        data = _mapping(raw, "build.image")
        _reject_unknown(data, {"formats", "size_mib", "output_directory"}, "build.image")
        formats_raw = data.get("formats")
        if not isinstance(formats_raw, list) or not formats_raw:
            raise ConfigurationValidationError("build.image.formats ha de ser una llista no buida")
        formats = tuple(
            _enum(ImageFormat, value, f"build.image.formats[{index}]")
            for index, value in enumerate(formats_raw)
        )
        if len(set(formats)) != len(formats):
            raise ConfigurationValidationError("build.image.formats conté valors duplicats")
        output = Path(_required_text(data, "output_directory", "build.image"))
        if output.is_absolute() or ".." in output.parts:
            raise ConfigurationValidationError(
                "build.image.output_directory ha de ser una ruta relativa segura"
            )
        return cls(
            formats=formats,
            size_mib=_positive_int(data, "size_mib", "build.image"),
            output_directory=output,
        )


@dataclass(frozen=True, slots=True)
class BuildConfig:
    """Top-level build definition."""

    schema_version: int
    project: str
    version: str
    architecture: Architecture
    channel: ReleaseChannel
    profile: str
    debian: DebianConfig
    image: ImageConfig

    @classmethod
    def from_mapping(cls, raw: object) -> Self:
        data = _mapping(raw, "build")
        _reject_unknown(
            data,
            {
                "schema_version",
                "project",
                "version",
                "architecture",
                "channel",
                "profile",
                "debian",
                "image",
            },
            "build",
        )
        schema_version = _positive_int(data, "schema_version", "build")
        if schema_version != 1:
            raise ConfigurationValidationError(
                f"build.schema_version={schema_version} no està suportada; s'espera 1"
            )
        version = _required_text(data, "version", "build")
        components = version.split(".")
        if len(components) != 3 or not all(part.isdigit() for part in components):
            raise ConfigurationValidationError("build.version ha de seguir MAJOR.MINOR.PATCH")
        return cls(
            schema_version=schema_version,
            project=_required_text(data, "project", "build"),
            version=version,
            architecture=_enum(Architecture, data.get("architecture"), "build.architecture"),
            channel=_enum(ReleaseChannel, data.get("channel"), "build.channel"),
            profile=_required_text(data, "profile", "build"),
            debian=DebianConfig.from_mapping(data.get("debian")),
            image=ImageConfig.from_mapping(data.get("image")),
        )


@dataclass(frozen=True, slots=True)
class PackageConfig:
    """Package groups and explicit exclusions."""

    base: tuple[str, ...]
    graphical: tuple[str, ...]
    xaac: tuple[str, ...]
    optional: tuple[str, ...]
    exclude: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: object) -> Self:
        data = _mapping(raw, "packages")
        allowed = {"base", "graphical", "xaac", "optional", "exclude"}
        _reject_unknown(data, allowed, "packages")
        config = cls(
            base=_text_tuple(data.get("base"), "packages.base", allow_empty=False),
            graphical=_text_tuple(data.get("graphical"), "packages.graphical"),
            xaac=_text_tuple(data.get("xaac"), "packages.xaac"),
            optional=_text_tuple(data.get("optional"), "packages.optional"),
            exclude=_text_tuple(data.get("exclude"), "packages.exclude"),
        )
        selected = set(config.base + config.graphical + config.xaac + config.optional)
        overlap = sorted(selected.intersection(config.exclude))
        if overlap:
            raise ConfigurationValidationError(
                f"packages.exclude també conté paquets seleccionats: {', '.join(overlap)}"
            )
        return config


@dataclass(frozen=True, slots=True)
class RepositoryConfig:
    """One signed APT repository definition."""

    name: str
    uri: str
    suites: tuple[str, ...]
    components: tuple[str, ...]
    signed_by: Path
    enabled: bool

    @classmethod
    def from_mapping(cls, raw: object, index: int) -> Self:
        location = f"repositories[{index}]"
        data = _mapping(raw, location)
        _reject_unknown(
            data, {"name", "uri", "suites", "components", "signed_by", "enabled"}, location
        )
        uri = _required_text(data, "uri", location)
        if not uri.startswith("https://"):
            raise ConfigurationValidationError(f"{location}.uri ha d'utilitzar HTTPS")
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigurationValidationError(f"{location}.enabled ha de ser booleà")
        signed_by = Path(_required_text(data, "signed_by", location))
        if not signed_by.is_absolute():
            raise ConfigurationValidationError(f"{location}.signed_by ha de ser una ruta absoluta")
        return cls(
            name=_required_text(data, "name", location),
            uri=uri.rstrip("/"),
            suites=_text_tuple(data.get("suites"), f"{location}.suites", allow_empty=False),
            components=_text_tuple(
                data.get("components"), f"{location}.components", allow_empty=False
            ),
            signed_by=signed_by,
            enabled=enabled,
        )


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    """Hardware profile with inheritance and resource limits."""

    name: str
    description: str
    extends: str | None
    architecture: Architecture
    memory_mib: int
    storage_mib: int
    kernel_parameters: tuple[str, ...]
    packages: tuple[str, ...]
    exclude_packages: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: object) -> Self:
        data = _mapping(raw, "profile")
        _reject_unknown(
            data,
            {
                "name",
                "description",
                "extends",
                "architecture",
                "memory_mib",
                "storage_mib",
                "kernel_parameters",
                "packages",
                "exclude_packages",
            },
            "profile",
        )
        return cls(
            name=_required_text(data, "name", "profile"),
            description=_required_text(data, "description", "profile"),
            extends=_optional_text(data, "extends", "profile"),
            architecture=_enum(Architecture, data.get("architecture"), "profile.architecture"),
            memory_mib=_positive_int(data, "memory_mib", "profile"),
            storage_mib=_positive_int(data, "storage_mib", "profile"),
            kernel_parameters=_text_tuple(
                data.get("kernel_parameters"), "profile.kernel_parameters"
            ),
            packages=_text_tuple(data.get("packages"), "profile.packages"),
            exclude_packages=_text_tuple(data.get("exclude_packages"), "profile.exclude_packages"),
        )
