from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from xaac_thin_client_os.firewall_configuration import create_firewall_configuration_plan
from xaac_thin_client_os.production_builder import ProductionIsoBuilder
from xaac_thin_client_os.ssh_configuration import create_ssh_configuration_plan


ROOT = Path(__file__).resolve().parents[1]


def test_production_rootfs_is_accepted_by_network_hardening_plans(tmp_path: Path) -> None:
    rootfs = tmp_path / ".build/production/rootfs"
    ssh = create_ssh_configuration_plan(rootfs, ROOT / "config/ssh.yaml")
    firewall = create_firewall_configuration_plan(
        rootfs,
        ROOT / "config/firewall.yaml",
        ROOT / "config/ssh.yaml",
    )

    assert ssh.rootfs == rootfs.resolve()
    assert firewall.rootfs == rootfs.resolve()


def test_production_policy_keeps_ssh_off_and_nftables_default_deny() -> None:
    ssh = yaml.safe_load((ROOT / "config/ssh.yaml").read_text(encoding="utf-8"))
    firewall = yaml.safe_load((ROOT / "config/firewall.yaml").read_text(encoding="utf-8"))

    assert ssh["enabled"] is False
    assert ssh["authentication"] == {
        "public_key": True,
        "password": False,
        "keyboard_interactive": False,
        "authorized_keys_directory": "/etc/xaac/ssh/authorized_keys",
        "allowed_key_types": ["ssh-ed25519", "sk-ssh-ed25519@openssh.com"],
    }
    assert firewall["enabled"] is True
    assert firewall["policy"]["input"] == "drop"
    assert firewall["policy"]["forward"] == "drop"


def test_production_builder_applies_and_verifies_network_hardening() -> None:
    configure = inspect.getsource(ProductionIsoBuilder.phase_configure)
    helper = inspect.getsource(ProductionIsoBuilder._configure_production_network_hardening)

    assert "self._configure_production_network_hardening()" in configure
    assert '["systemctl", "enable", "ssh.service"]' not in configure
    assert '["systemctl", "enable", "nftables.service"]' not in configure
    assert "create_ssh_configuration_plan" in helper
    assert "create_firewall_configuration_plan" in helper
    assert '["sshd", "-t"]' in helper
    assert '["nft", "-c", "-f", "/etc/nftables.conf"]' in helper
    assert "! systemctl is-enabled --quiet ssh.service" in helper
    assert "systemctl is-enabled --quiet nftables.service" in helper
    assert "grep -F 'policy drop' /etc/nftables.conf" in helper


def test_current_block9_document_defers_iso_until_final_consolidation() -> None:
    text = (ROOT / "docs/development/HARDENING_OPTIMIZATION.md").read_text(encoding="utf-8")

    assert "## Fase 9.1 — Línia base efectiva de xarxa" in text
    assert "Aquesta fase no genera ISO." in text
    assert "## Fase 9.4 — Consolidació, ISO única i validació física" in text
    assert "./scripts/build-production-iso.sh --clean" in text
