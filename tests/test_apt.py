from __future__ import annotations

from pathlib import Path

import pytest

from xaac_thin_client_os.apt import (
    AptConfigurationError,
    AptConfigurator,
    create_apt_configuration_plan,
)
from xaac_thin_client_os.configuration import load_project_configuration


def _plan(project_root: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    configuration = load_project_configuration(project_root)
    return create_apt_configuration_plan(
        tmp_path / "run" / "rootfs",
        configuration.repositories,
        configuration.build.architecture.value,
    )


def test_sources_are_rendered_as_deb822(project_root: Path, tmp_path: Path) -> None:
    sources = _plan(project_root, tmp_path).render_sources()
    assert "Types: deb" in sources
    assert "Suites: trixie" in sources
    assert "Components: main non-free-firmware" in sources
    assert "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" in sources


def test_minimal_policy_disables_recommends(project_root: Path, tmp_path: Path) -> None:
    policy = _plan(project_root, tmp_path).render_policy()
    assert 'APT::Install-Recommends "false";' in policy
    assert 'APT::Install-Suggests "false";' in policy
    assert 'Acquire::Languages "none";' in policy


def test_manifest_describes_effective_repositories(project_root: Path, tmp_path: Path) -> None:
    payload = _plan(project_root, tmp_path).to_manifest()
    assert payload["format"] == "deb822"
    assert payload["architecture"] == "amd64"
    assert payload["repositories"][0]["name"] == "debian"  # type: ignore[index]


def test_plan_rejects_top_level_rootfs(project_root: Path) -> None:
    configuration = load_project_configuration(project_root)
    with pytest.raises(AptConfigurationError, match="insegur"):
        create_apt_configuration_plan(Path("/rootfs"), configuration.repositories, "amd64")


def test_dry_run_needs_neither_rootfs_nor_root(project_root: Path, tmp_path: Path) -> None:
    plan = _plan(project_root, tmp_path)
    log = tmp_path / "logs" / "apt.log"
    result = AptConfigurator(geteuid=lambda: 1000).execute(plan, log, dry_run=True)
    assert result.executed is False
    assert result.files == ()
    assert "DRY-RUN" in log.read_text(encoding="utf-8")
    assert not plan.sources_path.exists()


def test_real_configuration_requires_root(project_root: Path, tmp_path: Path) -> None:
    with pytest.raises(AptConfigurationError, match="root"):
        AptConfigurator(geteuid=lambda: 1000).execute(
            _plan(project_root, tmp_path), tmp_path / "apt.log"
        )


def test_real_configuration_rejects_invalid_rootfs(project_root: Path, tmp_path: Path) -> None:
    with pytest.raises(AptConfigurationError, match="Debian vàlid"):
        AptConfigurator(geteuid=lambda: 0).execute(
            _plan(project_root, tmp_path), tmp_path / "apt.log"
        )


def test_real_configuration_requires_repository_keyring(project_root: Path, tmp_path: Path) -> None:
    plan = _plan(project_root, tmp_path)
    (plan.rootfs / "etc").mkdir(parents=True)
    (plan.rootfs / "etc" / "debian_version").write_text("13\n", encoding="utf-8")
    with pytest.raises(AptConfigurationError, match="keyring"):
        AptConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "apt.log")


def test_real_configuration_writes_expected_files(project_root: Path, tmp_path: Path) -> None:
    plan = _plan(project_root, tmp_path)
    (plan.rootfs / "etc").mkdir(parents=True)
    (plan.rootfs / "etc" / "debian_version").write_text("13\n", encoding="utf-8")
    keyring = plan.rootfs / "usr/share/keyrings/debian-archive-keyring.gpg"
    keyring.parent.mkdir(parents=True)
    keyring.write_bytes(b"keyring")
    result = AptConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "apt.log")
    assert result.executed
    assert len(result.files) == 3
    assert plan.sources_path.is_file()
    assert plan.policy_path.is_file()
    assert "Gestionat per XAAC" in plan.legacy_sources_path.read_text(encoding="utf-8")
    assert (plan.sources_path.stat().st_mode & 0o777) == 0o644


def test_refuses_sources_symlink(project_root: Path, tmp_path: Path) -> None:
    plan = _plan(project_root, tmp_path)
    (plan.rootfs / "etc").mkdir(parents=True)
    (plan.rootfs / "etc" / "debian_version").write_text("13\n", encoding="utf-8")
    keyring = plan.rootfs / "usr/share/keyrings/debian-archive-keyring.gpg"
    keyring.parent.mkdir(parents=True)
    keyring.write_bytes(b"keyring")
    plan.sources_path.parent.mkdir(parents=True)
    plan.sources_path.symlink_to(tmp_path / "outside")
    with pytest.raises(AptConfigurationError, match="enllaç simbòlic"):
        AptConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "apt.log")
