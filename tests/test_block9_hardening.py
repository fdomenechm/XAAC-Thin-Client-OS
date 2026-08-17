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
    installer = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")

    assert "self._configure_production_network_hardening()" in configure
    assert 'chroot "$mount_root" systemctl enable ssh.service' not in installer
    assert 'chroot "$mount_root" systemctl disable ssh.service' in installer
    assert "create_ssh_configuration_plan" in helper
    assert "create_firewall_configuration_plan" in helper
    assert '["sshd", "-t"]' in helper
    assert '["nft", "-c", "-f", "/etc/nftables.conf"]' in helper
    assert "! systemctl is-enabled --quiet ssh.service" in helper
    assert "systemctl is-enabled --quiet nftables.service" in helper
    assert "grep -F 'policy drop' /etc/nftables.conf" in helper


def test_phase_92_keeps_squashfs_available_for_live_and_installer() -> None:
    policy = yaml.safe_load((ROOT / "config/kernel-hardening.yaml").read_text(encoding="utf-8"))
    assert "squashfs" not in policy["module_policy"]["disabled"]
    assert "squashfs" in policy["module_policy"]["allowed_runtime"]


def test_phase_92_resource_profile_is_effective_and_emmc_oriented() -> None:
    resources = yaml.safe_load((ROOT / "config/resources.yaml").read_text(encoding="utf-8"))
    source = Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")

    assert resources["memory"]["zram"] == {
        "enabled": True,
        "size_percent": 50,
        "algorithm": "zstd",
        "priority": 100,
    }
    assert resources["memory"]["swappiness"] == 100
    assert resources["journald"]["storage"] == "volatile"
    assert resources["journald"]["runtime_max_use_mib"] == 32
    assert resources["storage"]["require_noatime"] is True
    assert resources["storage"]["trim_timer"] is True
    assert "apt-daily.timer" in resources["services"]["disabled"]
    assert "apt-daily-upgrade.timer" in resources["services"]["disabled"]
    assert 'UUID=$root_uuid / ext4 defaults,noatime 0 1' in source
    assert 'UUID=$data_uuid /data ext4 defaults,noatime 0 2' in source
    assert 'UUID=$recovery_uuid /recovery ext4 defaults,noatime 0 2' in source


def test_production_builder_applies_kernel_and_resource_policy_without_touching_host_sysctl() -> None:
    configure = inspect.getsource(ProductionIsoBuilder.phase_configure)
    helper = inspect.getsource(ProductionIsoBuilder._configure_production_kernel_resources)

    assert "self._configure_production_kernel_resources()" in configure
    assert "create_kernel_hardening_plan" in helper
    assert "KernelHardeningInstaller" in helper
    assert "create_resource_configuration_plan" in helper
    assert "ResourceConfigurator" in helper
    assert "sysctl --system" not in helper
    assert "sysctl -w" not in helper
    assert "configure-verify-kernel-resources" in helper
    assert "squashfs" in helper
    assert "fstrim.timer" in helper
    assert "tmp.mount" in helper
    assert "apt-daily.timer" in helper


def test_phase_92_removes_build_only_package_caches_before_squashfs() -> None:
    configure = inspect.getsource(ProductionIsoBuilder.phase_configure)
    assert "configure-clean-build-cache" in configure
    assert "apt-get clean" in configure
    assert "rm -rf /var/lib/apt/lists/* /tmp/xaac-packages" in configure


def test_current_block9_document_defers_iso_until_final_consolidation() -> None:
    text = (ROOT / "docs/development/HARDENING_OPTIMIZATION.md").read_text(encoding="utf-8")

    assert "## Fase 9.1 — Línia base efectiva de xarxa" in text
    assert "## Fase 9.2 — Kernel, memòria, eMMC i serveis mínims" in text
    assert "Fase 9.2 implementada" in text
    assert "No es genera ISO en aquesta fase." in text
    assert "## Fase 9.4 — Consolidació, ISO única i validació física" in text
    assert "./scripts/build-production-iso.sh --clean" in text
