from pathlib import Path
import json
import pytest

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.network_services import (
    NetworkServicesError, NetworkServicesManager, NetworkServicesRequest,
    create_network_services_plan, load_network_services_profile,
)


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "network-services.yaml"
    path.write_text(Path("config/network-services.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _plan(tmp_path: Path, request: NetworkServicesRequest):
    return create_network_services_plan(tmp_path / "rootfs", _profile(tmp_path), request)


def test_profile_selects_systemd_backends(tmp_path: Path) -> None:
    profile = load_network_services_profile(_profile(tmp_path))
    assert profile["backend"]["dns"] == "systemd-resolved"
    assert profile["backend"]["ntp"] == "systemd-timesyncd"


def test_profile_rejects_unsafe_path(tmp_path: Path) -> None:
    path = _profile(tmp_path)
    path.write_text(path.read_text().replace("/etc/xaac/network/proxy.env", "../proxy.env"), encoding="utf-8")
    with pytest.raises(NetworkServicesError, match="Ruta insegura"):
        load_network_services_profile(path)


def test_dns_domains_and_ntp_render(tmp_path: Path) -> None:
    plan = _plan(tmp_path, NetworkServicesRequest(dns=("192.0.2.53",), domains=("example.org",), ntp=("ntp.example.org",)))
    assert "DNS=192.0.2.53" in plan.files["resolved"]
    assert "Domains=example.org" in plan.files["resolved"]
    assert "NTP=ntp.example.org" in plan.files["timesyncd"]


def test_invalid_dns_and_domain_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(NetworkServicesError, match="DNS"):
        _plan(tmp_path, NetworkServicesRequest(dns=("bad host",)))
    with pytest.raises(NetworkServicesError, match="Domini"):
        _plan(tmp_path, NetworkServicesRequest(domains=("-bad.example",)))


def test_proxy_and_exceptions_render(tmp_path: Path) -> None:
    plan = _plan(tmp_path, NetworkServicesRequest(proxy="http://proxy.example.org:3128", no_proxy=("localhost", "example.org")))
    assert 'HTTP_PROXY="http://proxy.example.org:3128"' in plan.files["proxy_environment"]
    assert 'Proxy::example.org "DIRECT"' in plan.files["apt_proxy"]


def test_invalid_proxy_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(NetworkServicesError, match="proxy"):
        _plan(tmp_path, NetworkServicesRequest(proxy="socks5://proxy.example.org"))


def test_limits_are_enforced(tmp_path: Path) -> None:
    with pytest.raises(NetworkServicesError, match="límit"):
        _plan(tmp_path, NetworkServicesRequest(dns=("1.1.1.1", "8.8.8.8", "9.9.9.9", "192.0.2.53")))


def test_apply_writes_state_diagnostics_and_snapshot(tmp_path: Path) -> None:
    plan = _plan(tmp_path, NetworkServicesRequest(source="remote", dns=("192.0.2.53",), ntp=("ntp.example.org",)))
    paths = NetworkServicesManager().apply(plan)
    assert len(paths) == 7
    state = json.loads(plan.path("state").read_text(encoding="utf-8"))
    diagnostics = json.loads(plan.path("diagnostics").read_text(encoding="utf-8"))
    assert state["source"] == "remote"
    assert diagnostics["checks"]["dns_configured"] is True
    assert plan.path("snapshot").stat().st_mode & 0o777 == 0o600


def test_apply_is_idempotent_and_keeps_previous_snapshot(tmp_path: Path) -> None:
    manager = NetworkServicesManager()
    first = _plan(tmp_path, NetworkServicesRequest(dns=("1.1.1.1",)))
    manager.apply(first)
    second = _plan(tmp_path, NetworkServicesRequest(dns=("8.8.8.8",)))
    manager.apply(second)
    snapshot = json.loads(second.path("snapshot").read_text(encoding="utf-8"))
    assert "DNS=1.1.1.1" in snapshot["files"]["resolved"]


def test_rollback_restores_previous_configuration(tmp_path: Path) -> None:
    manager = NetworkServicesManager()
    first = _plan(tmp_path, NetworkServicesRequest(dns=("1.1.1.1",)))
    manager.apply(first)
    second = _plan(tmp_path, NetworkServicesRequest(dns=("8.8.8.8",)))
    manager.apply(second)
    manager.rollback(second)
    assert "DNS=1.1.1.1" in second.path("resolved").read_text(encoding="utf-8")
    assert json.loads(second.path("state").read_text(encoding="utf-8"))["status"] == "rolled-back"


def test_rollback_without_snapshot_fails(tmp_path: Path) -> None:
    with pytest.raises(NetworkServicesError, match="snapshot"):
        NetworkServicesManager().rollback(_plan(tmp_path, NetworkServicesRequest()))


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plan = _plan(tmp_path, NetworkServicesRequest(dns=("1.1.1.1",)))
    paths = NetworkServicesManager().apply(plan, dry_run=True)
    assert len(paths) == 6
    assert not any(path.exists() for path in paths)


def test_cli_exposes_network_services_options() -> None:
    args = build_parser().parse_args(["configure-network-services", "--source", "remote", "--dns", "1.1.1.1", "--domain", "example.org", "--ntp", "ntp.example.org", "--proxy", "http://proxy:3128", "--no-proxy", "localhost", "--dry-run"])
    assert args.source == "remote"
    assert args.dns == ["1.1.1.1"]
    assert args.dry_run is True
