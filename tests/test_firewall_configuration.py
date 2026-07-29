from pathlib import Path
import json
import pytest
from xaac_thin_client_os.firewall_configuration import FirewallConfigurationError, FirewallConfigurator, create_firewall_configuration_plan


def _firewall(path: Path) -> Path:
    path.write_text("""schema_version: 2
enabled: true
policy: {input: drop, forward: drop, output: accept}
allow: {loopback: true, established: true, dhcp_client: true, icmp: true}
management:
  sources: [10.0.0.0/8, '2001:db8::/32']
  ssh_from_config: true
  agent: {enabled: true, tcp_ports: [7443], udp_ports: []}
  rustdesk: {enabled: true, tcp_ports: [21115, 21116], udp_ports: [21116]}
state: {path: /var/lib/xaac-agent/network/firewall.json}
""", encoding="utf-8")
    return path


def _ssh(path: Path) -> Path:
    path.write_text("schema_version: 1\nenabled: true\nport: 2222\nallow_users: [xaac-admin]\nallowed_sources: [10.0.0.0/8]\nauthentication: {}\nhardening: {}\n", encoding="utf-8")
    return path


def _plan(tmp_path: Path):
    return create_firewall_configuration_plan(tmp_path / "runs/build/rootfs", _firewall(tmp_path / "firewall.yaml"), _ssh(tmp_path / "ssh.yaml"))


def test_plan_renders_default_drop_and_management_services(tmp_path: Path) -> None:
    text = _plan(tmp_path).ruleset_text()
    assert "policy drop" in text
    assert "ct state established,related accept" in text
    assert "tcp dport 2222" in text
    assert "tcp dport 7443" in text
    assert "tcp dport { 21115, 21116 }" in text
    assert "udp dport 21116" in text
    assert "management_sources_v4" in text and "management_sources_v6" in text


def test_manifest_exposes_agent_rustdesk_and_state(tmp_path: Path) -> None:
    manifest = _plan(tmp_path).to_manifest()
    assert manifest["management"]["agent"]["tcp_ports"] == [7443]
    assert manifest["management"]["rustdesk"]["udp_ports"] == [21116]
    assert manifest["state_path"].endswith("firewall.json")


def test_rejects_unsafe_rootfs(tmp_path: Path) -> None:
    with pytest.raises(FirewallConfigurationError, match="insegura"):
        create_firewall_configuration_plan(Path("/rootfs"), _firewall(tmp_path / "f.yaml"), _ssh(tmp_path / "s.yaml"))


def test_rejects_permissive_input_policy(tmp_path: Path) -> None:
    config = _firewall(tmp_path / "f.yaml")
    config.write_text(config.read_text().replace("input: drop", "input: accept"))
    with pytest.raises(FirewallConfigurationError, match="drop"):
        create_firewall_configuration_plan(tmp_path / "runs/build/rootfs", config, _ssh(tmp_path / "s.yaml"))


def test_rejects_invalid_management_network(tmp_path: Path) -> None:
    config = _firewall(tmp_path / "f.yaml")
    config.write_text(config.read_text().replace("10.0.0.0/8", "10.0.0.1/8"))
    with pytest.raises(FirewallConfigurationError, match="gestió"):
        create_firewall_configuration_plan(tmp_path / "runs/build/rootfs", config, _ssh(tmp_path / "s.yaml"))


def test_rejects_empty_management_networks(tmp_path: Path) -> None:
    config = _firewall(tmp_path / "f.yaml")
    config.write_text(config.read_text().replace("[10.0.0.0/8, '2001:db8::/32']", "[]"))
    with pytest.raises(FirewallConfigurationError, match="almenys"):
        create_firewall_configuration_plan(tmp_path / "runs/build/rootfs", config, _ssh(tmp_path / "s.yaml"))


def test_rejects_invalid_service_port(tmp_path: Path) -> None:
    config = _firewall(tmp_path / "f.yaml")
    config.write_text(config.read_text().replace("[7443]", "[70000]"))
    with pytest.raises(FirewallConfigurationError, match="Port no vàlid"):
        create_firewall_configuration_plan(tmp_path / "runs/build/rootfs", config, _ssh(tmp_path / "s.yaml"))


def test_disabled_service_does_not_open_declared_ports(tmp_path: Path) -> None:
    config = _firewall(tmp_path / "f.yaml")
    config.write_text(config.read_text().replace("agent: {enabled: true", "agent: {enabled: false"))
    plan = create_firewall_configuration_plan(tmp_path / "runs/build/rootfs", config, _ssh(tmp_path / "s.yaml"))
    assert "7443" not in plan.ruleset_text()


def test_dry_run_does_not_require_root(tmp_path: Path) -> None:
    result = FirewallConfigurator(geteuid=lambda: 1000).execute(_plan(tmp_path), tmp_path / "firewall.log", dry_run=True)
    assert result.executed is False
    assert "table inet xaac_filter" in result.log_path.read_text()


def test_real_execution_requires_root(tmp_path: Path) -> None:
    with pytest.raises(FirewallConfigurationError, match="root"):
        FirewallConfigurator(geteuid=lambda: 1000).execute(_plan(tmp_path), tmp_path / "firewall.log")


def test_writes_rules_state_and_enables_service(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    for name in ("etc/debian_version", "usr/lib/systemd/system/nftables.service", "usr/sbin/nft"):
        path = plan.rootfs / name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
    result = FirewallConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "firewall.log")
    rules, state = result.files_written
    assert rules.stat().st_mode & 0o777 == 0o600
    assert state.stat().st_mode & 0o777 == 0o640
    assert json.loads(state.read_text())["backend"] == "nftables"
    assert (plan.rootfs / "etc/systemd/system/multi-user.target.wants/nftables.service").is_symlink()


def test_apply_is_idempotent(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    for name in ("etc/debian_version", "usr/lib/systemd/system/nftables.service", "usr/sbin/nft"):
        path = plan.rootfs / name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
    configurator = FirewallConfigurator(geteuid=lambda: 0)
    configurator.execute(plan, tmp_path / "one.log")
    before = (plan.rootfs / "etc/nftables.conf").read_bytes()
    configurator.execute(plan, tmp_path / "two.log")
    assert (plan.rootfs / "etc/nftables.conf").read_bytes() == before


def test_rejects_unknown_schema_key(tmp_path: Path) -> None:
    config = _firewall(tmp_path / "f.yaml"); config.write_text(config.read_text() + "unknown: true\n")
    with pytest.raises(FirewallConfigurationError, match="esquema"):
        create_firewall_configuration_plan(tmp_path / "runs/build/rootfs", config, _ssh(tmp_path / "s.yaml"))


def test_rejects_symbolic_rules_file(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    for name in ("etc/debian_version", "usr/lib/systemd/system/nftables.service", "usr/sbin/nft"):
        path = plan.rootfs / name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
    target = plan.rootfs / "tmp/rules"; target.parent.mkdir(parents=True, exist_ok=True); target.touch()
    rules = plan.rootfs / "etc/nftables.conf"; rules.parent.mkdir(parents=True, exist_ok=True); rules.symlink_to(target)
    with pytest.raises(FirewallConfigurationError, match="enllaç simbòlic"):
        FirewallConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "firewall.log")


def test_rejects_unsafe_state_path(tmp_path: Path) -> None:
    config = _firewall(tmp_path / "f.yaml")
    config.write_text(config.read_text().replace("/var/lib/xaac-agent/network/firewall.json", "/tmp/firewall.json"))
    with pytest.raises(FirewallConfigurationError, match="estat"):
        create_firewall_configuration_plan(tmp_path / "runs/build/rootfs", config, _ssh(tmp_path / "s.yaml"))
