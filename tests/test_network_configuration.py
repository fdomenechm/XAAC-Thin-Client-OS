from pathlib import Path
import pytest
from xaac_thin_client_os.network_configuration import NetworkConfigurationError, NetworkConfigurator, create_network_configuration_plan

def _config(path: Path, extra: str='') -> Path:
    path.write_text('''schema_version: 1
backend: systemd-networkd
interface_match: "en*"
dhcp4: true
dhcp6: false
ipv6_accept_ra: false
required_for_online: true
dns:
  use_resolved: true
  fallback: [1.1.1.1, 9.9.9.9]
'''+extra, encoding='utf-8'); return path

def _plan(tmp_path: Path): return create_network_configuration_plan(tmp_path/'runs/build/rootfs', _config(tmp_path/'network.yaml'))

def test_plan_and_render(tmp_path: Path):
    plan=_plan(tmp_path); assert plan.interface_match=='en*'; assert 'DHCP=ipv4' in plan.network_text(); assert plan.fallback_dns==('1.1.1.1','9.9.9.9')

def test_unsafe_rootfs(tmp_path: Path):
    with pytest.raises(NetworkConfigurationError, match='insegura'): create_network_configuration_plan(Path('/rootfs'), _config(tmp_path/'network.yaml'))

def test_invalid_backend(tmp_path: Path):
    p=_config(tmp_path/'network.yaml'); p.write_text(p.read_text().replace('systemd-networkd','NetworkManager'))
    with pytest.raises(NetworkConfigurationError, match='systemd-networkd'): create_network_configuration_plan(tmp_path/'runs/build/rootfs',p)

def test_invalid_dns(tmp_path: Path):
    p=_config(tmp_path/'network.yaml'); p.write_text(p.read_text().replace('1.1.1.1','invalid'))
    with pytest.raises(NetworkConfigurationError, match='DNS fallback'): create_network_configuration_plan(tmp_path/'runs/build/rootfs',p)

def test_dry_run(tmp_path: Path):
    result=NetworkConfigurator(geteuid=lambda:1000).execute(_plan(tmp_path),tmp_path/'log',dry_run=True); assert not result.executed

def test_requires_root(tmp_path: Path):
    with pytest.raises(NetworkConfigurationError, match='root'): NetworkConfigurator(geteuid=lambda:1000).execute(_plan(tmp_path),tmp_path/'log')

def test_requires_systemd(tmp_path: Path):
    with pytest.raises(NetworkConfigurationError, match='falten'): NetworkConfigurator(geteuid=lambda:0).execute(_plan(tmp_path),tmp_path/'log')

def test_writes_configuration_and_links(tmp_path: Path):
    plan=_plan(tmp_path)
    for name in ('etc/debian_version','usr/lib/systemd/system/systemd-networkd.service','usr/lib/systemd/system/systemd-resolved.service'):
        p=plan.rootfs/name; p.parent.mkdir(parents=True,exist_ok=True); p.touch()
    result=NetworkConfigurator(geteuid=lambda:0).execute(plan,tmp_path/'log')
    assert result.executed; assert (plan.rootfs/'etc/systemd/network/20-xaac-wired.network').exists(); assert (plan.rootfs/'etc/resolv.conf').is_symlink(); assert (plan.rootfs/'etc/systemd/system/multi-user.target.wants/systemd-networkd.service').is_symlink()
