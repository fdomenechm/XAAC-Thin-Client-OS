import pytest

from xaac_thin_client_os.runtime import UnsupportedPythonError, ensure_supported_python


def test_python_313_is_supported() -> None:
    ensure_supported_python((3, 13, 0))


@pytest.mark.parametrize("version", [(3, 12, 9), (3, 14, 0), (2, 7, 18)])
def test_other_python_versions_are_rejected(version: tuple[int, int, int]) -> None:
    with pytest.raises(UnsupportedPythonError, match="requereix Python 3.13"):
        ensure_supported_python(version)
