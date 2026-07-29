from pathlib import Path

from xaac_thin_client_os import PROJECT_NAME, __version__


def test_project_name() -> None:
    assert PROJECT_NAME == "XAAC Thin Client OS"


def test_version_matches_version_file() -> None:
    expected = Path("VERSION").read_text(encoding="utf-8").strip()
    assert __version__ == expected


def test_version_has_three_numeric_components() -> None:
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
