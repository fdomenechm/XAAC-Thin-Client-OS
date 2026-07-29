from __future__ import annotations

import pytest

from xaac_thin_client_os.build_dependencies import (
    DEBIAN_BUILD_PACKAGES,
    REQUIRED_BUILD_COMMANDS,
    BuildDependencyError,
    inspect_build_dependencies,
    require_build_dependencies,
)


def test_inspect_build_dependencies_reports_all_available() -> None:
    report = inspect_build_dependencies(search=lambda command: f"/usr/bin/{command}")
    assert report.available == REQUIRED_BUILD_COMMANDS
    assert report.missing == ()


def test_inspect_build_dependencies_reports_missing_in_stable_order() -> None:
    missing = {"debootstrap", "grub-install", "rsync"}
    report = inspect_build_dependencies(
        search=lambda command: None if command in missing else f"/usr/bin/{command}"
    )
    assert report.missing == tuple(command for command in REQUIRED_BUILD_COMMANDS if command in missing)


def test_require_build_dependencies_returns_report_when_complete() -> None:
    report = require_build_dependencies(search=lambda command: f"/usr/bin/{command}")
    assert not report.missing


def test_require_build_dependencies_lists_commands_and_install_command() -> None:
    with pytest.raises(BuildDependencyError) as captured:
        require_build_dependencies(search=lambda command: None if command == "debootstrap" else "/bin/tool")
    message = str(captured.value)
    assert "debootstrap" in message
    assert "sudo apt install" in message
    assert all(package in message for package in DEBIAN_BUILD_PACKAGES)
