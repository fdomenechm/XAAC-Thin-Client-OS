from pathlib import Path

import pytest

from xaac_thin_client_os.configuration import (
    ConfigurationFileError,
    ConfigurationValidationError,
    load_project_configuration,
    load_repositories,
    load_yaml,
)


def test_project_configuration_loads_from_repository() -> None:
    configuration = load_project_configuration(Path("."))
    assert configuration.build.profile == "wyse3040"
    assert configuration.profile.memory_mib == 2048
    assert configuration.profile.storage_mib == 8192
    assert configuration.packages.base[0] == "systemd"
    assert configuration.repositories[0].name == "debian"


def test_missing_yaml_file_has_context(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationFileError, match="No s'ha pogut llegir"):
        load_yaml(tmp_path / "absent.yaml")


def test_invalid_yaml_has_context(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("key: [not closed", encoding="utf-8")
    with pytest.raises(ConfigurationFileError, match="YAML invàlid"):
        load_yaml(path)


def test_repository_document_rejects_duplicate_names() -> None:
    entry = {
        "name": "debian",
        "uri": "https://deb.debian.org/debian",
        "suites": ["trixie"],
        "components": ["main"],
        "signed_by": "/usr/share/keyrings/debian-archive-keyring.gpg",
    }
    with pytest.raises(ConfigurationValidationError, match="noms duplicats"):
        load_repositories({"repositories": [entry, dict(entry)]})


def test_repository_document_rejects_wrong_root() -> None:
    with pytest.raises(ConfigurationValidationError, match="únicament"):
        load_repositories({"sources": []})


def test_cross_validation_rejects_version_mismatch(tmp_path: Path) -> None:
    import shutil

    shutil.copytree("config", tmp_path / "config")
    shutil.copytree("profiles", tmp_path / "profiles")
    build = tmp_path / "config" / "build.yaml"
    build.write_text(build.read_text(encoding="utf-8").replace("1.0.0", "9.9.9"), encoding="utf-8")
    with pytest.raises(ConfigurationValidationError, match="no coincideix amb VERSION"):
        load_project_configuration(tmp_path)


def test_cross_validation_rejects_oversized_image(tmp_path: Path) -> None:
    import shutil

    shutil.copytree("config", tmp_path / "config")
    shutil.copytree("profiles", tmp_path / "profiles")
    build = tmp_path / "config" / "build.yaml"
    build.write_text(build.read_text(encoding="utf-8").replace("7168", "9000"), encoding="utf-8")
    with pytest.raises(ConfigurationValidationError, match="supera l'emmagatzematge"):
        load_project_configuration(tmp_path)


def test_repository_document_rejects_empty_entries() -> None:
    with pytest.raises(ConfigurationValidationError, match="llista no buida"):
        load_repositories({"repositories": []})


def _copy_configuration_tree(tmp_path: Path) -> None:
    import shutil

    shutil.copytree("config", tmp_path / "config")
    shutil.copytree("profiles", tmp_path / "profiles")


def test_cross_validation_rejects_project_mismatch(tmp_path: Path) -> None:
    _copy_configuration_tree(tmp_path)
    build = tmp_path / "config" / "build.yaml"
    build.write_text(
        build.read_text(encoding="utf-8").replace("XAAC Thin Client OS", "Other OS"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationValidationError, match="build.project"):
        load_project_configuration(tmp_path)


def test_cross_validation_rejects_architecture_mismatch(tmp_path: Path) -> None:
    _copy_configuration_tree(tmp_path)
    profile = tmp_path / "profiles" / "wyse3040" / "profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("architecture: amd64", "architecture: arm64"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationValidationError, match="valor desconegut"):
        load_project_configuration(tmp_path)


def test_cross_validation_rejects_profile_name_mismatch(tmp_path: Path) -> None:
    _copy_configuration_tree(tmp_path)
    profile = tmp_path / "profiles" / "wyse3040" / "profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("name: wyse3040", "name: wrong"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationValidationError, match="profile.name"):
        load_project_configuration(tmp_path)
