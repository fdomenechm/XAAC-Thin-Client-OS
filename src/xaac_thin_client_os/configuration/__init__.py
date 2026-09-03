"""Public API for project configuration."""

from xaac_thin_client_os.configuration.errors import (
    ConfigurationError,
    ConfigurationFileError,
    ConfigurationValidationError,
)
from xaac_thin_client_os.configuration.loader import (
    ProjectConfiguration,
    load_project_configuration,
    load_repositories,
    load_yaml,
)
from xaac_thin_client_os.configuration.model import (
    Architecture,
    BuildConfig,
    DebianConfig,
    HardwareProfile,
    ImageConfig,
    ImageFormat,
    PackageConfig,
    ReleaseChannel,
    RepositoryConfig,
)

__all__ = [
    "Architecture",
    "BuildConfig",
    "ConfigurationError",
    "ConfigurationFileError",
    "ConfigurationValidationError",
    "DebianConfig",
    "HardwareProfile",
    "ImageConfig",
    "ImageFormat",
    "PackageConfig",
    "ProjectConfiguration",
    "ReleaseChannel",
    "RepositoryConfig",
    "load_project_configuration",
    "load_repositories",
    "load_yaml",
]
