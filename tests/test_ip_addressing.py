from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.ip_addressing import (
    IpAddressingError, IpAddressingManager, IpAddressingRequest,
    create_ip_addressing_plan, load_ip_addressing_profile,
)


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "ip-addressing.yaml"
    path.write_text(Path("config/ip-addressing.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _plan(tmp_path: Path, request: IpAddressingRequest):
    return create_ip_addressing_plan(tmp_path / "rootfs", _profile(tmp_path), request)


def test_profile_requires_safe_dhcp_fallback(tmp_path: Path) -> None:
    profile = load_ip_addressing_profile(_profile(tmp_path))
    assert profile["fallback"] == {"enabled": True, "mode": "dhcp"}


def test_profile_rejects_unknown_backend(tmp_path: Path) -> None:
    path = _profile(tmp_path)
    path.write_text(path.read_text().replace("systemd-networkd", "NetworkManager"), encoding="utf-8")
    with pytest.raises(IpAddressingError, match="Backend"):
        load_ip_addressing_profile(path)


def test_dhcp_plan_is_minimal(tmp_path: Path) -> None:
    plan = _plan(tmp_path, IpAddressingRequest("local", "dhcp"))
    assert "DHCP=ipv4" in plan.network_text
    assert "Address=" not in plan.network_text


def test_dhcp_rejects_static_fields(tmp_path: Path) -> None:
    with pytest.raises(IpAddressingError, match="no admet"):
        _plan(tmp_path, IpAddressingRequest("local", "dhcp", address="192.0.2.10/24"))


def test_static_plan_validates_and_renders(tmp_path: Path) -> None:
    plan = _plan(tmp_path, IpAddressingRequest("remote", "static", "192.0.2.10/24", "192.0.2.1", ("192.0.2.53",)))
    assert "Address=192.0.2.10/24" in plan.network_text
    assert "Gateway=192.0.2.1" in plan.network_text
    assert "DNS=192.0.2.53" in plan.network_text


def test_static_gateway_must_be_in_subnet(tmp_path: Path) -> None:
    with pytest.raises(IpAddressingError, match="subxarxa"):
        _plan(tmp_path, IpAddressingRequest("remote", "static", "192.0.2.10/24", "198.51.100.1"))


def test_static_dns_limit_and_syntax(tmp_path: Path) -> None:
    with pytest.raises(IpAddressingError, match="Massa"):
        _plan(tmp_path, IpAddressingRequest("local", "static", "192.0.2.10/24", "192.0.2.1", ("1.1.1.1", "8.8.8.8", "9.9.9.9", "192.0.2.53")))
    with pytest.raises(IpAddressingError, match="DNS invàlid"):
        _plan(tmp_path, IpAddressingRequest("local", "static", "192.0.2.10/24", "192.0.2.1", ("bad",)))


def test_apply_creates_state_and_snapshot(tmp_path: Path) -> None:
    dhcp = _plan(tmp_path, IpAddressingRequest("local", "dhcp"))
    manager = IpAddressingManager()
    manager.apply(dhcp)
    static = _plan(tmp_path, IpAddressingRequest("remote", "static", "192.0.2.10/24", "192.0.2.1"))
    manager.apply(static)
    state = json.loads(static.path("state").read_text(encoding="utf-8"))
    assert state["source"] == "remote"
    assert state["rollback_available"] is True
    assert len(list(static.path("snapshots").glob("*.network"))) == 1


def test_rollback_restores_previous_network(tmp_path: Path) -> None:
    manager = IpAddressingManager()
    dhcp = _plan(tmp_path, IpAddressingRequest("local", "dhcp"))
    manager.apply(dhcp)
    static = _plan(tmp_path, IpAddressingRequest("remote", "static", "192.0.2.10/24", "192.0.2.1"))
    manager.apply(static)
    manager.rollback(static)
    assert "DHCP=ipv4" in static.path("active_network").read_text(encoding="utf-8")
    assert json.loads(static.path("state").read_text(encoding="utf-8"))["status"] == "rolled-back"


def test_rollback_without_snapshot_fails(tmp_path: Path) -> None:
    plan = _plan(tmp_path, IpAddressingRequest("local", "dhcp"))
    with pytest.raises(IpAddressingError, match="snapshot"):
        IpAddressingManager().rollback(plan)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = _plan(tmp_path, IpAddressingRequest("local", "dhcp"))
    paths = IpAddressingManager().apply(plan, dry_run=True)
    assert len(paths) == 3
    assert not any(path.exists() for path in paths)


def test_cli_exposes_local_remote_and_rollback() -> None:
    args = build_parser().parse_args(["configure-ip-addressing", "--source", "remote", "--mode", "static", "--address", "192.0.2.10/24", "--gateway", "192.0.2.1", "--rollback", "--dry-run"])
    assert args.source == "remote"
    assert args.rollback is True
    assert args.dry_run is True
