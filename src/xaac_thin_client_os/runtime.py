"""Runtime compatibility checks."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from xaac_thin_client_os.metadata import SUPPORTED_PYTHON


class UnsupportedPythonError(RuntimeError):
    """Raised when the program runs with an unsupported Python version."""


def ensure_supported_python(version_info: Sequence[int] | None = None) -> None:
    """Require the exact supported Python major and minor release."""
    current = tuple((version_info or sys.version_info)[:2])
    if current != SUPPORTED_PYTHON:
        expected = ".".join(map(str, SUPPORTED_PYTHON))
        actual = ".".join(map(str, current))
        raise UnsupportedPythonError(
            f"XAAC Thin Client OS requereix Python {expected}; versió detectada: {actual}."
        )
