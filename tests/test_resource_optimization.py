from __future__ import annotations
import json
from pathlib import Path
import pytest
from xaac_thin_client_os.resource_optimization import *

def write(root,rel,text):
 p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
def inv(**kw):
 d=dict(total_memory_mib=1984,available_memory_mib=1500,swap_total_mib=992,zram_devices=('zram0',),root_free_mib=1024,root_mount_options=('rw','noatime'),journald_persistent=False);d.update(kw);return ResourceInventory(**d)
def test_detector(tmp_path):
 write(tmp_path,'proc/meminfo','MemTotal: 2031616 kB\nMemAvailable: 1536000 kB\nSwapTotal: 1015808 kB\n');write(tmp_path,'proc/mounts','/dev/mmcblk0p2 / ext4 rw,noatime 0 0\n');write(tmp_path,'__root_statvfs__','1024');(tmp_path/'sys/block/zram0').mkdir(parents=True)
 r=ResourceDetector(root=tmp_path).detect();assert r.total_memory_mib==1984 and r.zram_devices==('zram0',)
def test_missing_safe(tmp_path): assert ResourceDetector(root=tmp_path).detect().total_memory_mib==0
def test_profile(project_root): assert load_resource_profile(project_root/'config/resources.yaml')['profile']=='wyse3040'
@pytest.mark.parametrize('text',['[]\n','schema_version: 2\n','schema_version: 1\nprofile: x\n'])
def test_invalid_profile(tmp_path,text):
 p=tmp_path/'p.yaml';p.write_text(text)
 with pytest.raises(ResourceOptimizationError):load_resource_profile(p)
def test_invalid_zram(tmp_path,project_root):
 import yaml;p=load_resource_profile(project_root/'config/resources.yaml');p['memory']['zram']['size_percent']=101;f=tmp_path/'p.yaml';f.write_text(yaml.safe_dump(p))
 with pytest.raises(ResourceOptimizationError):load_resource_profile(f)
def test_compatible(project_root): assert compare_resources(inv(),load_resource_profile(project_root/'config/resources.yaml')).compatible
def test_low_memory_fails(project_root): assert not compare_resources(inv(total_memory_mib=1024),load_resource_profile(project_root/'config/resources.yaml')).compatible
def test_missing_zram_warns(project_root):
 r=compare_resources(inv(zram_devices=()),load_resource_profile(project_root/'config/resources.yaml'));assert r.compatible and any(c.name=='zram' and c.status=='warning' for c in r.checks)
def test_low_space_warns(project_root): assert compare_resources(inv(root_free_mib=100),load_resource_profile(project_root/'config/resources.yaml')).compatible
def test_noatime_warns(project_root): assert compare_resources(inv(root_mount_options=('rw',)),load_resource_profile(project_root/'config/resources.yaml')).compatible
def test_persistent_journal_warns(project_root): assert compare_resources(inv(journald_persistent=True),load_resource_profile(project_root/'config/resources.yaml')).compatible
def test_plan(project_root,tmp_path):
 p=create_resource_configuration_plan(tmp_path/'build/rootfs',project_root/'config/resources.yaml');assert 'systemd-zram-generator' in p.packages and len(p.files)==7 and len(p.enabled_units)==2
def test_execute(project_root,tmp_path):
 p=create_resource_configuration_plan(tmp_path/'build/rootfs',project_root/'config/resources.yaml');w=ResourceConfigurator().execute(p);assert len(w)==14;assert 'zram-size' in w[0].read_text();assert w[-1].is_symlink();assert (p.rootfs/'etc/systemd/system/local-fs.target.wants/tmp.mount').readlink()==Path('/lib/systemd/system/tmp.mount');assert (p.rootfs/'etc/systemd/system/timers.target.wants/fstrim.timer').readlink()==Path('/lib/systemd/system/fstrim.timer')
def test_dry_run(project_root,tmp_path): assert ResourceConfigurator().execute(create_resource_configuration_plan(tmp_path/'build/rootfs',project_root/'config/resources.yaml'),dry_run=True)==()
def test_unsafe(project_root):
 with pytest.raises(ResourceOptimizationError):create_resource_configuration_plan(Path('/'),project_root/'config/resources.yaml')
def test_symlink(project_root,tmp_path):
 p=create_resource_configuration_plan(tmp_path/'build/rootfs',project_root/'config/resources.yaml');t=p.rootfs/'etc/xaac/resource-policy.json';t.parent.mkdir(parents=True);t.symlink_to(tmp_path/'x')
 with pytest.raises(ResourceOptimizationError):ResourceConfigurator().execute(p)
def test_conflict(project_root,tmp_path):
 p=create_resource_configuration_plan(tmp_path/'build/rootfs',project_root/'config/resources.yaml');t=p.rootfs/'etc/systemd/system/apt-daily.service';t.parent.mkdir(parents=True);t.write_text('x')
 with pytest.raises(ResourceOptimizationError):ResourceConfigurator().execute(p)
def test_report(project_root,tmp_path):
 d=tmp_path/'r.json';write_resource_report(compare_resources(inv(),load_resource_profile(project_root/'config/resources.yaml')),d);assert json.loads(d.read_text())['compatible']
def test_parser(project_root):
 from xaac_thin_client_os.cli import build_parser
 assert build_parser().parse_args(['--root',str(project_root),'configure-resources','--dry-run']).command=='configure-resources'
def test_cli(monkeypatch,project_root,capsys):
 from xaac_thin_client_os.cli import main
 monkeypatch.setattr('xaac_thin_client_os.cli.ResourceDetector.detect',lambda self:inv());assert main(['--root',str(project_root),'--json','inspect-resources'])==0;assert json.loads(capsys.readouterr().out)['compatible']
