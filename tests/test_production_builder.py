from __future__ import annotations

from pathlib import Path

import pytest

from xaac_thin_client_os.production_builder import (
    BuildPaths,
    CommandRunner,
    ProductionBuildError,
    ProductionIsoBuilder,
    build_parser,
)


def minimal_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\nversion='1'\n", encoding="utf-8")
    return root


def test_build_paths_rejects_non_project(tmp_path: Path) -> None:
    with pytest.raises(ProductionBuildError):
        BuildPaths.create(tmp_path)


def test_build_paths_are_scoped_to_project(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    paths = BuildPaths.create(root)
    assert paths.rootfs == root / ".build/production/rootfs"
    assert paths.artifacts == root / ".build/artifacts"


def test_parser_accepts_individual_phases() -> None:
    args = build_parser().parse_args(["--phase", "rootfs", "--phase", "configure", "--dry-run"])
    assert args.phase == ["rootfs", "configure"]
    assert args.dry_run is True


def test_command_runner_dry_run_records_command(tmp_path: Path) -> None:
    runner = CommandRunner(tmp_path / "logs", dry_run=True)
    runner.run(["echo", "hello"], phase="sample")
    assert (tmp_path / "logs/sample.log").read_text(encoding="utf-8") == "$ echo hello\n"


def test_command_runner_recreates_logs_after_workspace_cleanup(tmp_path: Path) -> None:
    logs = tmp_path / "production/logs"
    runner = CommandRunner(logs, dry_run=True)
    import shutil
    shutil.rmtree(logs.parent)
    runner.run(["echo", "hello"], phase="after-clean")
    assert (logs / "after-clean.log").read_text(encoding="utf-8") == "$ echo hello\n"


def test_inside_never_uses_host_system_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    assert builder._inside("/usr/lib/systemd/system/getty@.service") == (
        root / ".build/production/rootfs/usr/lib/systemd/system/getty@.service"
    )
    with pytest.raises(ProductionBuildError):
        builder._inside("../../etc/passwd")


def test_clean_is_limited_to_production_workspace(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    builder = object.__new__(ProductionIsoBuilder)
    builder.paths = BuildPaths.create(root)  # type: ignore[misc]
    target = builder.paths.build_root
    target.mkdir(parents=True)
    (target / "file").write_text("x", encoding="utf-8")
    builder.clean()
    assert not target.exists()
