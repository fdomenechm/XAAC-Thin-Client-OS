from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.network_manager import (
    NetworkManagerConfigurator, NetworkManagerError, create_network_manager_plan,
    load_network_manager_profile,
)


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "network-manager.yaml"
    path.write_text(Path("config/network-manager.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _plan(tmp_path: Path):
    return create_network_manager_plan(tmp_path / "rootfs", _profile(tmp_path))


def test_profile_selects_networkd_definitively(tmp_path: Path) -> None:
    profile = load_network_manager_profile(_profile(tmp_path))
    assert profile["manager"]["backend"] == "systemd-networkd"
    assert profile["manager"]["exclusive"] is True


def test_profile_rejects_networkmanager(tmp_path: Path) -> None:
    path = _profile(tmp_path)
    path.write_text(path.read_text().replace("systemd-networkd", "NetworkManager"), encoding="utf-8")
    with pytest.raises(NetworkManagerError, match="systemd-networkd"):
        load_network_manager_profile(path)


def test_plan_rejects_unsafe_rootfs(tmp_path: Path) -> None:
    with pytest.raises(NetworkManagerError, match="insegur"):
        create_network_manager_plan(Path("/"), _profile(tmp_path))


def test_base_ethernet_rendering(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert "Type=ether" in plan.network_text()
    assert "DHCP=ipv4" in plan.network_text()
    assert "RequiredForOnline=yes" in plan.network_text()


def test_dry_run_is_non_destructive(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    paths = NetworkManagerConfigurator().install(plan, dry_run=True)
    assert len(paths) == 6
    assert not any(path.exists() for path in paths)


def test_install_writes_agent_status_and_systemd_links(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    paths = NetworkManagerConfigurator().install(plan)
    status = json.loads(plan.path("agent_status").read_text(encoding="utf-8"))
    assert status["format"] == "xaac-network-status"
    assert status["state"] == "unknown"
    assert plan.path("service_dropin").exists()
    assert (plan.rootfs / "etc/systemd/system/multi-user.target.wants/systemd-networkd.service").is_symlink()
    assert len(paths) == 6


def test_install_is_idempotent(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    configurator = NetworkManagerConfigurator()
    configurator.install(plan)
    before = plan.path("manager_manifest").read_text(encoding="utf-8")
    configurator.install(plan)
    assert plan.path("manager_manifest").read_text(encoding="utf-8") == before


def test_install_rejects_symlink_target(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    target = plan.path("agent_status")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(NetworkManagerError, match="enllaç simbòlic"):
        NetworkManagerConfigurator().install(plan)


def test_cli_exposes_network_manager_command() -> None:
    args = build_parser().parse_args(["configure-network-manager", "--dry-run"])
    assert args.command == "configure-network-manager"
    assert args.dry_run is True
