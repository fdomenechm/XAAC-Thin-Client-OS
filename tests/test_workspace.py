from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xaac_thin_client_os.workspace import (
    WorkspaceError,
    WorkspaceLockedError,
    WorkspaceManager,
)


def test_build_id_is_sortable_and_unique(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("xaac_thin_client_os.workspace.token_hex", lambda _: "abcdef12")
    build_id = WorkspaceManager.create_build_id(datetime(2026, 7, 28, 8, 9, 10, tzinfo=UTC))
    assert build_id == "20260728T080910Z-abcdef12"


def test_prepare_creates_isolated_workspace(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    with manager:
        workspace = manager.prepare({"project": "XAAC", "version": "0.1.0"})
        assert workspace.logs_dir.is_dir()
        assert workspace.artifacts_dir.is_dir()
        assert workspace.temporary_dir.is_dir()
        assert workspace.rendered_dir.is_dir()
        manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "prepared"
        assert manifest["build_id"] == workspace.build_id
        assert manager.current() == workspace
    assert not manager.lock_path.exists()


def test_prepare_requires_lock(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="bloqueig"):
        WorkspaceManager(tmp_path).prepare({})


def test_lock_prevents_concurrent_builds(tmp_path: Path) -> None:
    first = WorkspaceManager(tmp_path)
    second = WorkspaceManager(tmp_path)
    first.acquire_lock()
    try:
        with pytest.raises(WorkspaceLockedError):
            second.acquire_lock()
        assert first.read_lock() is not None
    finally:
        first.release_lock()


def test_release_without_lock_is_safe(tmp_path: Path) -> None:
    WorkspaceManager(tmp_path).release_lock()


def test_current_rejects_invalid_pointer(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.build_root.mkdir()
    manager.current_path.write_text("../escape\n", encoding="utf-8")
    assert manager.current() is None


def test_clean_removes_workspace(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.build_root.mkdir()
    assert manager.clean() is True
    assert manager.clean() is False


def test_clean_refuses_locked_workspace(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.acquire_lock()
    try:
        with pytest.raises(WorkspaceLockedError):
            WorkspaceManager(tmp_path).clean()
    finally:
        manager.release_lock()
