"""Project metadata shared by commands and tests."""

from pathlib import Path

PROJECT_NAME = "XAAC Thin Client OS"
SUPPORTED_PYTHON = (3, 13)


def _read_version() -> str:
    """Read the canonical version from the repository VERSION file.

    Installed wheels may not contain the repository root. In that case the package
    version constant remains the authoritative fallback for this initial phase.
    """
    repository_version = Path(__file__).resolve().parents[2] / "VERSION"
    if repository_version.is_file():
        value = repository_version.read_text(encoding="utf-8").strip()
        if value:
            return value
    return "0.1.0"


__version__ = _read_version()
