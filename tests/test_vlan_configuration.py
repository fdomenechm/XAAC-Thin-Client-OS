from pathlib import Path
import json, pytest
from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.vlan_configuration import *

def prof(tmp_path):
 p=tmp_path/'vlan.yaml'; p.write_text(Path('config/vlan.yaml').read_text()); return p
def plan(tmp_path,**kw): return create_vlan_plan(tmp_path/'rootfs',prof(tmp_path),VlanRequest(**kw))
def test_profile(): assert load_vlan_profile(Path('config/vlan.yaml'))['backend']=='systemd-networkd'
def test_vlan_renders_8021q(tmp_path):
 p=plan(tmp_path,vlan_id=100); assert 'Kind=vlan' in p.files['netdev'] and 'Id=100' in p.files['netdev'] and 'VLAN=vlan100' in p.files['parent']
def test_static_vlan(tmp_path):
 p=plan(tmp_path,vlan_id=20,mode='static',address='192.0.2.10/24',gateway='192.0.2.1',dns=('192.0.2.53',)); assert 'Address=192.0.2.10/24' in p.files['network']
def test_invalid_ids(tmp_path):
 for vid in (0,4095):
  with pytest.raises(VlanConfigurationError,match='política'): plan(tmp_path,vlan_id=vid)
def test_invalid_name_and_parent(tmp_path):
 with pytest.raises(VlanConfigurationError,match='Nom'): plan(tmp_path,vlan_id=2,name='bad name')
 with pytest.raises(VlanConfigurationError,match='pare'): plan(tmp_path,vlan_id=2,parent='eth0')
def test_static_requires_address(tmp_path):
 with pytest.raises(VlanConfigurationError,match='requereix'): plan(tmp_path,vlan_id=2,mode='static')
def test_apply_state_and_pending_cleanup(tmp_path):
 p=plan(tmp_path,source='remote',vlan_id=200); paths=VlanManager().apply(p); assert len(paths)==6; assert not p.path('pending').exists(); assert json.loads(p.path('state').read_text())['source']=='remote'
def test_apply_is_idempotent_and_snapshots(tmp_path):
 p=plan(tmp_path,vlan_id=200); m=VlanManager(); m.apply(p); p.target('network').write_text('old\n'); m.apply(p); assert 'old' in p.path('snapshot').read_text()
def test_rollback_removes_new_vlan(tmp_path):
 p=plan(tmp_path,vlan_id=300); m=VlanManager(); m.apply(p); m.rollback(p); assert not p.target('netdev').exists(); assert json.loads(p.path('state').read_text())['status']=='rolled-back'
def test_rollback_without_snapshot(tmp_path):
 with pytest.raises(VlanConfigurationError,match='snapshot'): VlanManager().rollback(plan(tmp_path,vlan_id=10))
def test_dry_run(tmp_path):
 p=plan(tmp_path,vlan_id=10); paths=VlanManager().apply(p,dry_run=True); assert not any(x.exists() for x in paths)
def test_cli_vlan_options():
 a=build_parser().parse_args(['configure-vlan','--source','remote','--vlan-id','100','--mode','dhcp','--dry-run']); assert a.vlan_id==100 and a.source=='remote' and a.dry_run
