import os
from pathlib import Path

import pytest

from xaac_thin_client_os.hooks import (
    HOOK_PHASES,
    HookExecutionError,
    HookPermissionError,
    HookPhase,
    HookRunner,
    HookTimeoutError,
)


def _hook(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + body + "\n", encoding="utf-8")
    path.chmod(0o750)
    return path


def test_supported_phases_have_stable_order() -> None:
    assert [phase.value for phase in HOOK_PHASES] == [
        "pre-bootstrap",
        "post-bootstrap",
        "pre-packages",
        "post-packages",
        "pre-image",
        "post-image",
    ]


def test_missing_phase_is_optional(tmp_path: Path) -> None:
    assert HookRunner(tmp_path, tmp_path / "logs").run_phase(HookPhase.PRE_IMAGE) == ()


def test_discovery_is_sorted_and_ignores_hidden_files(tmp_path: Path) -> None:
    _hook(tmp_path / "hooks/pre-image/20-second", "echo second")
    _hook(tmp_path / "hooks/pre-image/10-first", "echo first")
    (tmp_path / "hooks/pre-image/.gitkeep").touch()
    found = HookRunner(tmp_path, tmp_path / "logs").discover(HookPhase.PRE_IMAGE)
    assert [item.name for item in found] == ["10-first", "20-second"]


def test_discovery_ignores_directory_readme(tmp_path: Path) -> None:
    phase_dir = tmp_path / "hooks" / HookPhase.PRE_IMAGE.value
    phase_dir.mkdir(parents=True)
    (phase_dir / "README.md").write_text("# Hooks\n", encoding="utf-8")

    found = HookRunner(tmp_path, tmp_path / "logs").discover(HookPhase.PRE_IMAGE)

    assert found == ()


def test_non_executable_hook_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "hooks/pre-image/hook"
    path.parent.mkdir(parents=True)
    path.write_text("echo no", encoding="utf-8")
    with pytest.raises(HookPermissionError, match="execució"):
        HookRunner(tmp_path, tmp_path / "logs").discover(HookPhase.PRE_IMAGE)


def test_symlink_hook_is_rejected(tmp_path: Path) -> None:
    target = _hook(tmp_path / "target", "echo target")
    phase = tmp_path / "hooks/pre-image"
    phase.mkdir(parents=True)
    (phase / "link").symlink_to(target)
    with pytest.raises(HookPermissionError, match="simbòlics"):
        HookRunner(tmp_path, tmp_path / "logs").discover(HookPhase.PRE_IMAGE)


def test_hook_receives_environment_and_writes_log(tmp_path: Path) -> None:
    _hook(
        tmp_path / "hooks/pre-bootstrap/10-env",
        'printf "%s|%s|%s" "$XAAC_HOOK_PHASE" "$XAAC_BUILD_ID" "$XAAC_PROJECT_ROOT"',
    )
    runner = HookRunner(tmp_path, tmp_path / "logs", environment={"XAAC_BUILD_ID": "build-1"})
    result = runner.run_phase(HookPhase.PRE_BOOTSTRAP)[0]
    assert result.return_code == 0
    assert result.log_path.read_text(encoding="utf-8") == (
        f"pre-bootstrap|build-1|{tmp_path.resolve()}"
    )


def test_failing_hook_stops_phase_and_preserves_output(tmp_path: Path) -> None:
    _hook(tmp_path / "hooks/post-packages/fail", "echo failure >&2; exit 7")
    runner = HookRunner(tmp_path, tmp_path / "logs")
    with pytest.raises(HookExecutionError, match="codi 7"):
        runner.run_phase(HookPhase.POST_PACKAGES)
    assert "failure" in (tmp_path / "logs/hooks/post-packages/fail.log").read_text()


def test_hook_timeout_is_reported(tmp_path: Path) -> None:
    _hook(tmp_path / "hooks/post-image/slow", "sleep 1")
    runner = HookRunner(tmp_path, tmp_path / "logs", timeout_seconds=0.01)
    with pytest.raises(HookTimeoutError, match="timeout"):
        runner.run_phase(HookPhase.POST_IMAGE)


def test_invalid_timeout_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="superior a zero"):
        HookRunner(tmp_path, tmp_path / "logs", timeout_seconds=0)
