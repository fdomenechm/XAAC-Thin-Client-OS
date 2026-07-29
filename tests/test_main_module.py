import runpy

import pytest


def test_module_entry_point(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.argv", ["xaac_thin_client_os", "version"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("xaac_thin_client_os", run_name="__main__")
    assert exc_info.value.code == 0
