from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaac_thin_client_os.configuration import (
    ConfigurationValidationError,
    load_project_configuration,
)
from xaac_thin_client_os.packages import load_profile_chain, resolve_packages


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_resolve_project_packages(project_root: Path) -> None:
    configuration = load_project_configuration(project_root)
    resolved = resolve_packages(project_root, configuration)
    assert resolved.profile_chain == ("common", "wyse3040")
    assert resolved.packages == tuple(sorted(resolved.packages))
    assert "systemd" in resolved.packages
    assert "firmware-linux" in resolved.packages
    assert "task-desktop" in resolved.excluded
    assert len(resolved.packages) == len(set(resolved.packages))


def test_manifest_is_json_serialisable(project_root: Path) -> None:
    resolved = resolve_packages(project_root, load_project_configuration(project_root))
    payload = resolved.to_manifest()
    assert json.loads(json.dumps(payload))["package_count"] == len(resolved.packages)
    assert list(payload["sources"]) == [
        "base",
        "graphical",
        "xaac",
        "optional",
        "profile:common",
        "profile:wyse3040",
    ]


def test_profile_exclusion_removes_global_package(tmp_path: Path, project_root: Path) -> None:
    import shutil

    root = tmp_path / "project"
    shutil.copytree(project_root, root)
    profile = root / "profiles/wyse3040/profile.yaml"
    profile.write_text(
        profile.read_text().replace("exclude_packages: []", "exclude_packages:\n  - locales"),
        encoding="utf-8",
    )
    resolved = resolve_packages(root, load_project_configuration(root))
    assert "locales" not in resolved.packages
    assert "locales" in resolved.excluded


def test_duplicate_across_groups_is_deduplicated(tmp_path: Path, project_root: Path) -> None:
    import shutil

    root = tmp_path / "project"
    shutil.copytree(project_root, root)
    packages = root / "config/packages.yaml"
    packages.write_text(packages.read_text().replace("graphical: []", "graphical:\n  - systemd"))
    resolved = resolve_packages(root, load_project_configuration(root))
    assert resolved.packages.count("systemd") == 1


def test_missing_parent_profile_is_rejected(tmp_path: Path, project_root: Path) -> None:
    import shutil

    root = tmp_path / "project"
    shutil.copytree(project_root, root)
    profile = root / "profiles/wyse3040/profile.yaml"
    profile.write_text(profile.read_text().replace("extends: common", "extends: absent"))
    configuration = load_project_configuration(root)
    with pytest.raises(ConfigurationValidationError, match="no existeix"):
        resolve_packages(root, configuration)


def test_profile_cycle_is_rejected(tmp_path: Path, project_root: Path) -> None:
    import shutil

    root = tmp_path / "project"
    shutil.copytree(project_root, root)
    common = root / "profiles/common/profile.yaml"
    common.write_text(
        common.read_text().replace("architecture:", "extends: wyse3040\narchitecture:")
    )
    configuration = load_project_configuration(root)
    with pytest.raises(ConfigurationValidationError, match="Cicle"):
        resolve_packages(root, configuration)


def test_profile_name_must_match_directory(tmp_path: Path, project_root: Path) -> None:
    import shutil

    root = tmp_path / "project"
    shutil.copytree(project_root, root)
    common = root / "profiles/common/profile.yaml"
    common.write_text(common.read_text().replace("name: common", "name: other"))
    configuration = load_project_configuration(root)
    with pytest.raises(ConfigurationValidationError, match="no coincideix"):
        resolve_packages(root, configuration)


def test_same_profile_cannot_include_and_exclude_package(
    tmp_path: Path, project_root: Path
) -> None:
    import shutil

    root = tmp_path / "project"
    shutil.copytree(project_root, root)
    profile = root / "profiles/wyse3040/profile.yaml"
    profile.write_text(
        profile.read_text().replace("exclude_packages: []", "exclude_packages:\n  - firmware-linux")
    )
    configuration = load_project_configuration(root)
    with pytest.raises(ConfigurationValidationError, match="inclou i exclou"):
        resolve_packages(root, configuration)


def test_load_profile_chain_accepts_root_profile(project_root: Path) -> None:
    configuration = load_project_configuration(project_root)
    chain = load_profile_chain(project_root, configuration.profile)
    assert [profile.name for profile in chain] == ["common", "wyse3040"]
