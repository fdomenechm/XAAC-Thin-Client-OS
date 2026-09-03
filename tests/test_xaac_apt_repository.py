from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.xaac_apt_repository import (
    XaacAptRepositoryError,
    XaacAptRepositoryInstaller,
    create_xaac_apt_repository_plan,
    load_xaac_apt_repository,
)

ROOT = Path(__file__).parents[1]


def rootfs(tmp_path: Path) -> Path:
    path = tmp_path / ".build" / "rootfs"
    path.mkdir(parents=True)
    return path


def altered(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "repository.yaml"
    path.write_text((ROOT / "config/xaac-apt-repository.yaml").read_text().replace(old, new), encoding="utf-8")
    return path


def test_loads_repository_channels() -> None:
    policy = load_xaac_apt_repository(ROOT / "config/xaac-apt-repository.yaml")
    assert [item["suite"] for item in policy["channels"]] == ["laboratory", "pilot", "stable"]
    assert policy["metadata"]["hashes"] == ["SHA256", "SHA512"]


def test_manifest_is_stable(tmp_path: Path) -> None:
    plan = create_xaac_apt_repository_plan(rootfs(tmp_path), ROOT / "config/xaac-apt-repository.yaml")
    assert plan.manifest() == {"schema_version": 1, "repository_id": "xaac-apt", "channel_count": 3, "component_count": 1, "architecture_count": 1}


def test_installs_layout_metadata_and_mirror(tmp_path: Path) -> None:
    plan = create_xaac_apt_repository_plan(rootfs(tmp_path), ROOT / "config/xaac-apt-repository.yaml")
    policy, layout, distributions, mirror, state = XaacAptRepositoryInstaller().install(plan)
    assert json.loads(layout.read_text())["channels"]["production"] == "stable"
    assert "SignWith: 0123456789ABCDEF0123456789ABCDEF01234567" in distributions.read_text()
    assert json.loads(mirror.read_text())["verify_signatures"] is True
    assert json.loads(state.read_text())["status"] == "configured"
    assert policy.stat().st_mode & 0o777 == 0o644
    assert distributions.stat().st_mode & 0o777 == 0o640


def test_installation_is_idempotent(tmp_path: Path) -> None:
    plan = create_xaac_apt_repository_plan(rootfs(tmp_path), ROOT / "config/xaac-apt-repository.yaml")
    installer = XaacAptRepositoryInstaller(); paths = installer.install(plan)
    before = tuple(path.read_bytes() for path in paths); installer.install(plan)
    assert before == tuple(path.read_bytes() for path in paths)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = create_xaac_apt_repository_plan(rootfs(tmp_path), ROOT / "config/xaac-apt-repository.yaml")
    paths = XaacAptRepositoryInstaller().install(plan, dry_run=True)
    assert len(paths) == 5 and not any(path.exists() for path in paths)


def test_rejects_duplicate_suites(tmp_path: Path) -> None:
    path = altered(tmp_path, "suite: pilot", "suite: laboratory")
    with pytest.raises(XaacAptRepositoryError, match="duplicats"):
        load_xaac_apt_repository(path)


def test_rejects_unsigned_publication(tmp_path: Path) -> None:
    path = altered(tmp_path, "allow_unsigned: false", "allow_unsigned: true")
    with pytest.raises(XaacAptRepositoryError, match="sense signatura"):
        load_xaac_apt_repository(path)


def test_rejects_weak_hash(tmp_path: Path) -> None:
    path = altered(tmp_path, "hashes: [SHA256, SHA512]", "hashes: [SHA1, SHA256]")
    with pytest.raises(XaacAptRepositoryError, match="hashes"):
        load_xaac_apt_repository(path)


def test_rejects_insecure_mirror(tmp_path: Path) -> None:
    path = altered(tmp_path, "verify_signatures: true", "verify_signatures: false")
    with pytest.raises(XaacAptRepositoryError, match="verificar signatures"):
        load_xaac_apt_repository(path)


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    plan = create_xaac_apt_repository_plan(rootfs(tmp_path), ROOT / "config/xaac-apt-repository.yaml")
    target = plan.output("state"); target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(XaacAptRepositoryError, match="enllaç simbòlic"):
        XaacAptRepositoryInstaller().install(plan)


def test_cli_supports_repository_configuration(tmp_path: Path) -> None:
    assert build_parser().parse_args(["configure-xaac-apt-repository", "--dry-run"]).command == "configure-xaac-apt-repository"
    rootfs(tmp_path); (tmp_path / "config").mkdir()
    (tmp_path / "config/xaac-apt-repository.yaml").write_text((ROOT / "config/xaac-apt-repository.yaml").read_text())
    assert main(["--root", str(tmp_path), "configure-xaac-apt-repository", "--dry-run"]) == 0
