from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNTIME_PATH = ROOT / "assets/runtime/xaac_update_runtime.py"


def _load_runtime():
    spec = importlib.util.spec_from_file_location("xaac_update_runtime_config_restore", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_10_2_runtime_exposes_configuration_only_restore() -> None:
    runtime = _load_runtime()
    assert callable(runtime.restore_latest_configuration)
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    body = source[source.index("def restore_latest_configuration"):source.index("def recover_interrupted")]
    assert "_latest_recovery_point" in body
    assert "_restore_configuration" in body
    assert "manual_configuration_restore_completed" in body
