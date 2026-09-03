"""Errors produced while loading and validating build configuration."""


class ConfigurationError(ValueError):
    """Base error for invalid or unreadable project configuration."""


class ConfigurationFileError(ConfigurationError):
    """Raised when a configuration file cannot be read or decoded."""


class ConfigurationValidationError(ConfigurationError):
    """Raised when decoded configuration does not satisfy the schema."""
