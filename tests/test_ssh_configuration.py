from pathlib import Path
import stat
import pytest

from xaac_thin_client_os.ssh_configuration import (
    SshConfigurationError, SshConfigurator, create_ssh_configuration_plan,
)


def _config(path: Path) -> Path:
    path.write_text("""schema_version: 2
enabled: false
port: 22
allow_users: [xaac-admin]
allowed_sources: [10.0.0.0/8, 192.168.0.0/16]
authentication:
  public_key: true
  password: false
  keyboard_interactive: false
  authorized_keys_directory: /etc/xaac/ssh/authorized_keys
  allowed_key_types: [ssh-ed25519, sk-ssh-ed25519@openssh.com]
hardening:
  permit_root_login: false
  x11_forwarding: false
  tcp_forwarding: false
  agent_forwarding: false
  permit_tunnel: false
  max_auth_tries: 3
  login_grace_time: 30
  client_alive_interval: 300
  client_alive_count_max: 2
temporary_activation:
  enabled: true
  default_duration_seconds: 900
  minimum_duration_seconds: 60
  maximum_duration_seconds: 3600
  state_path: /var/lib/xaac/ssh/access-state.json
  helper_path: /usr/local/sbin/xaac-ssh-access
audit:
  rules_path: /etc/audit/rules.d/45-xaac-ssh.rules
  log_level: VERBOSE
""", encoding="utf-8")
    return path


def _plan(tmp_path: Path):
    return create_ssh_configuration_plan(tmp_path / "runs/build/rootfs", _config(tmp_path / "ssh.yaml"))


def _requirements(plan) -> None:
    for name in ("etc/debian_version", "usr/lib/systemd/system/ssh.service", "usr/sbin/sshd"):
        path = plan.rootfs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def test_plan_renders_key_only_hardening(tmp_path: Path) -> None:
    text = _plan(tmp_path).sshd_text()
    assert "AuthenticationMethods publickey" in text
    assert "PasswordAuthentication no" in text
    assert "PermitRootLogin no" in text
    assert "AuthorizedKeysFile /etc/xaac/ssh/authorized_keys/%u" in text


def test_plan_normalizes_authorized_sources(tmp_path: Path) -> None:
    assert _plan(tmp_path).allowed_sources == ("10.0.0.0/8", "192.168.0.0/16")


def test_rejects_unsafe_rootfs(tmp_path: Path) -> None:
    with pytest.raises(SshConfigurationError, match="insegura"):
        create_ssh_configuration_plan(Path("/rootfs"), _config(tmp_path / "ssh.yaml"))


def test_rejects_password_authentication(tmp_path: Path) -> None:
    config = _config(tmp_path / "ssh.yaml")
    config.write_text(config.read_text().replace("password: false", "password: true"))
    with pytest.raises(SshConfigurationError, match="clau pública"):
        create_ssh_configuration_plan(tmp_path / "runs/build/rootfs", config)


@pytest.mark.parametrize("user", ["root", "xaac-kiosk", "xaac-agent"])
def test_rejects_privileged_or_service_users(tmp_path: Path, user: str) -> None:
    config = _config(tmp_path / "ssh.yaml")
    config.write_text(config.read_text().replace("xaac-admin", user))
    with pytest.raises(SshConfigurationError, match="no autoritzat"):
        create_ssh_configuration_plan(tmp_path / "runs/build/rootfs", config)


def test_rejects_invalid_network(tmp_path: Path) -> None:
    config = _config(tmp_path / "ssh.yaml")
    config.write_text(config.read_text().replace("10.0.0.0/8", "10.0.0.1/8"))
    with pytest.raises(SshConfigurationError, match="Xarxa SSH"):
        create_ssh_configuration_plan(tmp_path / "runs/build/rootfs", config)


def test_rejects_unknown_key_type(tmp_path: Path) -> None:
    config = _config(tmp_path / "ssh.yaml")
    config.write_text(config.read_text().replace("ssh-ed25519,", "ssh-dss,"))
    with pytest.raises(SshConfigurationError, match="Tipus de clau"):
        create_ssh_configuration_plan(tmp_path / "runs/build/rootfs", config)


def test_rejects_activation_duration_outside_policy(tmp_path: Path) -> None:
    config = _config(tmp_path / "ssh.yaml")
    config.write_text(config.read_text().replace("default_duration_seconds: 900", "default_duration_seconds: 4000"))
    with pytest.raises(SshConfigurationError, match="default_duration_seconds"):
        create_ssh_configuration_plan(tmp_path / "runs/build/rootfs", config)


def test_helper_enforces_expiry_and_logs(tmp_path: Path) -> None:
    helper = _plan(tmp_path).helper_text()
    assert "systemd-run --unit=xaac-ssh-expire" in helper
    assert "systemctl stop ssh.service" in helper
    assert "logger -t xaac-ssh-access" in helper


def test_dry_run_does_not_require_root(tmp_path: Path) -> None:
    result = SshConfigurator(geteuid=lambda: 1000).execute(_plan(tmp_path), tmp_path / "ssh.log", dry_run=True)
    assert not result.executed
    assert result.files_written == ()


def test_real_execution_requires_root(tmp_path: Path) -> None:
    with pytest.raises(SshConfigurationError, match="root"):
        SshConfigurator(geteuid=lambda: 1000).execute(_plan(tmp_path), tmp_path / "ssh.log")


def test_writes_restricted_policy_and_keeps_service_disabled(tmp_path: Path) -> None:
    plan = _plan(tmp_path); _requirements(plan)
    result = SshConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "ssh.log")
    assert result.executed
    assert not (plan.rootfs / "etc/systemd/system/multi-user.target.wants/ssh.service").exists()
    key_file = plan.rootfs / "etc/xaac/ssh/authorized_keys/xaac-admin"
    helper = plan.rootfs / "usr/local/sbin/xaac-ssh-access"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(helper.stat().st_mode) == 0o750
    assert "temporary access" in helper.read_text()


def test_enabled_policy_creates_service_link(tmp_path: Path) -> None:
    config = _config(tmp_path / "ssh.yaml")
    config.write_text(config.read_text().replace("enabled: false", "enabled: true", 1))
    plan = create_ssh_configuration_plan(tmp_path / "runs/build/rootfs", config); _requirements(plan)
    SshConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "ssh.log")
    assert (plan.rootfs / "etc/systemd/system/multi-user.target.wants/ssh.service").is_symlink()


def test_apply_is_idempotent_with_read_only_managed_files(tmp_path: Path) -> None:
    plan = _plan(tmp_path); _requirements(plan)
    manager = SshConfigurator(geteuid=lambda: 0)
    manager.execute(plan, tmp_path / "one.log")
    manager.execute(plan, tmp_path / "two.log")
    assert (plan.rootfs / "etc/ssh/sshd_config.d/20-xaac-hardening.conf").read_text() == plan.sshd_text()


def test_rejects_symlink_for_managed_file(tmp_path: Path) -> None:
    plan = _plan(tmp_path); _requirements(plan)
    target = plan.rootfs / "etc/ssh/sshd_config.d/20-xaac-hardening.conf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(SshConfigurationError, match="enllaç simbòlic"):
        SshConfigurator(geteuid=lambda: 0).execute(plan, tmp_path / "ssh.log")
