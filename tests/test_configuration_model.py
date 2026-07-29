from pathlib import Path

import pytest

from xaac_thin_client_os.configuration import (
    Architecture,
    BuildConfig,
    ConfigurationValidationError,
    HardwareProfile,
    ImageFormat,
    PackageConfig,
    ReleaseChannel,
    RepositoryConfig,
)


def valid_build() -> dict[str, object]:
    return {
        "schema_version": 1,
        "project": "XAAC Thin Client OS",
        "version": "0.1.0",
        "architecture": "amd64",
        "channel": "development",
        "profile": "wyse3040",
        "debian": {
            "suite": "trixie",
            "mirror": "https://deb.debian.org/debian",
            "components": ["main"],
        },
        "image": {"formats": ["img"], "size_mib": 7168, "output_directory": "dist"},
    }


def test_build_configuration_is_typed() -> None:
    config = BuildConfig.from_mapping(valid_build())
    assert config.architecture is Architecture.AMD64
    assert config.channel is ReleaseChannel.DEVELOPMENT
    assert config.image.formats == (ImageFormat.IMG,)
    assert config.image.output_directory == Path("dist")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 2, "no està suportada"),
        ("version", "1.0", "MAJOR.MINOR.PATCH"),
        ("architecture", "arm64", "valor desconegut"),
        ("channel", "nightly", "valor desconegut"),
    ],
)
def test_invalid_build_scalar_values_are_rejected(field: str, value: object, message: str) -> None:
    raw = valid_build()
    raw[field] = value
    with pytest.raises(ConfigurationValidationError, match=message):
        BuildConfig.from_mapping(raw)


def test_unknown_build_field_is_rejected() -> None:
    raw = valid_build()
    raw["unexpected"] = True
    with pytest.raises(ConfigurationValidationError, match="camps desconeguts"):
        BuildConfig.from_mapping(raw)


def test_insecure_mirror_is_rejected() -> None:
    raw = valid_build()
    assert isinstance(raw["debian"], dict)
    raw["debian"]["mirror"] = "http://example.invalid/debian"
    with pytest.raises(ConfigurationValidationError, match="HTTPS"):
        BuildConfig.from_mapping(raw)


def test_unsafe_output_directory_is_rejected() -> None:
    raw = valid_build()
    assert isinstance(raw["image"], dict)
    raw["image"]["output_directory"] = "../outside"
    with pytest.raises(ConfigurationValidationError, match="ruta relativa segura"):
        BuildConfig.from_mapping(raw)


def test_duplicate_image_formats_are_rejected() -> None:
    raw = valid_build()
    assert isinstance(raw["image"], dict)
    raw["image"]["formats"] = ["img", "img"]
    with pytest.raises(ConfigurationValidationError, match="duplicats"):
        BuildConfig.from_mapping(raw)


def test_package_selection_cannot_also_be_excluded() -> None:
    with pytest.raises(ConfigurationValidationError, match="també conté"):
        PackageConfig.from_mapping(
            {
                "base": ["systemd"],
                "graphical": [],
                "xaac": [],
                "optional": [],
                "exclude": ["systemd"],
            }
        )


def test_repository_requires_https_and_absolute_keyring() -> None:
    raw = {
        "name": "xaac",
        "uri": "https://repo.example.org",
        "suites": ["stable"],
        "components": ["main"],
        "signed_by": "/usr/share/keyrings/xaac.gpg",
    }
    repository = RepositoryConfig.from_mapping(raw, 0)
    assert repository.enabled is True

    raw["signed_by"] = "keys/xaac.gpg"
    with pytest.raises(ConfigurationValidationError, match="ruta absoluta"):
        RepositoryConfig.from_mapping(raw, 0)


def test_hardware_profile_supports_optional_inheritance() -> None:
    profile = HardwareProfile.from_mapping(
        {
            "name": "wyse3040",
            "description": "Dell Wyse 3040",
            "extends": "common",
            "architecture": "amd64",
            "memory_mib": 2048,
            "storage_mib": 8192,
            "kernel_parameters": [],
            "packages": [],
            "exclude_packages": [],
        }
    )
    assert profile.extends == "common"


def test_basic_type_validation_errors() -> None:
    with pytest.raises(ConfigurationValidationError, match="ha de ser un mapa"):
        BuildConfig.from_mapping([])
    with pytest.raises(ConfigurationValidationError, match="claus de text"):
        BuildConfig.from_mapping({1: "bad"})


def test_required_and_optional_text_validation() -> None:
    raw = valid_build()
    raw["project"] = ""
    with pytest.raises(ConfigurationValidationError, match="text no buit"):
        BuildConfig.from_mapping(raw)

    profile_raw = {
        "name": "common",
        "description": "Common",
        "extends": "",
        "architecture": "amd64",
        "memory_mib": 2048,
        "storage_mib": 8192,
        "kernel_parameters": [],
        "packages": [],
        "exclude_packages": [],
    }
    with pytest.raises(ConfigurationValidationError, match="extends ha de ser text no buit"):
        HardwareProfile.from_mapping(profile_raw)


def test_positive_integer_and_enum_type_validation() -> None:
    raw = valid_build()
    raw["schema_version"] = True
    with pytest.raises(ConfigurationValidationError, match="enter positiu"):
        BuildConfig.from_mapping(raw)

    raw = valid_build()
    raw["architecture"] = 42
    with pytest.raises(ConfigurationValidationError, match="ha de ser text"):
        BuildConfig.from_mapping(raw)


def test_list_validation_rejects_invalid_empty_and_duplicate_values() -> None:
    raw = valid_build()
    assert isinstance(raw["debian"], dict)
    raw["debian"]["components"] = "main"
    with pytest.raises(ConfigurationValidationError, match="ha de ser una llista"):
        BuildConfig.from_mapping(raw)

    raw = valid_build()
    assert isinstance(raw["debian"], dict)
    raw["debian"]["components"] = []
    with pytest.raises(ConfigurationValidationError, match="no pot estar buida"):
        BuildConfig.from_mapping(raw)

    raw = valid_build()
    assert isinstance(raw["debian"], dict)
    raw["debian"]["components"] = [""]
    with pytest.raises(ConfigurationValidationError, match="text no buit"):
        BuildConfig.from_mapping(raw)

    raw = valid_build()
    assert isinstance(raw["debian"], dict)
    raw["debian"]["components"] = ["main", "main"]
    with pytest.raises(ConfigurationValidationError, match="duplicat"):
        BuildConfig.from_mapping(raw)


def test_optional_package_lists_default_to_empty() -> None:
    config = PackageConfig.from_mapping({"base": ["systemd"]})
    assert config.graphical == ()
    assert config.exclude == ()


def test_empty_or_invalid_image_formats_are_rejected() -> None:
    raw = valid_build()
    assert isinstance(raw["image"], dict)
    raw["image"]["formats"] = []
    with pytest.raises(ConfigurationValidationError, match="llista no buida"):
        BuildConfig.from_mapping(raw)


def test_repository_rejects_insecure_uri_and_non_boolean_enabled() -> None:
    raw = {
        "name": "xaac",
        "uri": "http://repo.example.org",
        "suites": ["stable"],
        "components": ["main"],
        "signed_by": "/usr/share/keyrings/xaac.gpg",
    }
    with pytest.raises(ConfigurationValidationError, match="HTTPS"):
        RepositoryConfig.from_mapping(raw, 0)

    raw["uri"] = "https://repo.example.org"
    raw["enabled"] = "yes"
    with pytest.raises(ConfigurationValidationError, match="booleà"):
        RepositoryConfig.from_mapping(raw, 0)
