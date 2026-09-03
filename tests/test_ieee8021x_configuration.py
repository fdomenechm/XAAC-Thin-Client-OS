from pathlib import Path
import json, stat, pytest
from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.ieee8021x_configuration import *

def profile(tmp_path):
 p=tmp_path/'ieee.yaml'; p.write_text(Path('config/ieee8021x.yaml').read_text()); return p
def plan(tmp_path,**kw):
 defaults=dict(identity='device@example.org',ca_certificate='/etc/xaac/certificates/ca.pem',client_certificate='/etc/xaac/certificates/client.pem',private_key='/etc/xaac/certificates/client.key')
 defaults.update(kw); return create_ieee8021x_plan(tmp_path/'rootfs',profile(tmp_path),Ieee8021xRequest(**defaults))
def test_profile(): assert load_ieee8021x_profile(Path('config/ieee8021x.yaml'))['backend']=='wpa_supplicant'
def test_tls_render(tmp_path):
 p=plan(tmp_path); assert 'eap=TLS' in p.files['supplicant'] and 'client_cert=' in p.files['supplicant']
def test_peap_render_and_secret_separation(tmp_path):
 p=plan(tmp_path,eap='peap',password='secret',client_certificate=None,private_key=None); assert '${PASSWORD}' in p.files['supplicant'] and 'secret' not in p.files['supplicant'] and 'PASSWORD=secret' in p.files['credentials']
def test_tls_requires_material(tmp_path):
 with pytest.raises(Ieee8021xError,match='Certificat client'): plan(tmp_path,client_certificate=None)
def test_peap_requires_password(tmp_path):
 with pytest.raises(Ieee8021xError,match='contrasenya'): plan(tmp_path,eap='peap',client_certificate=None,private_key=None)
def test_rejects_certificate_outside_policy(tmp_path):
 with pytest.raises(Ieee8021xError,match='autoritzat'): plan(tmp_path,ca_certificate='/tmp/ca.pem')
def test_rejects_interface_and_source(tmp_path):
 with pytest.raises(Ieee8021xError,match='Interfície'): plan(tmp_path,interface='eth0')
 with pytest.raises(Ieee8021xError,match='Font'): plan(tmp_path,source='other')
def test_rejects_injection(tmp_path):
 with pytest.raises(Ieee8021xError,match='Identitat'): plan(tmp_path,identity='bad\nvalue')
def test_apply_state_permissions_and_renewal(tmp_path):
 p=plan(tmp_path,source='remote'); paths=Ieee8021xManager().apply(p); assert len(paths)==7; assert not p.path('pending').exists(); assert json.loads(p.path('state').read_text())['source']=='remote'; assert stat.S_IMODE(p.path('credentials').stat().st_mode)==0o600; assert json.loads(p.path('renewal').read_text())['managed_by']=='xaac-agent'
def test_apply_snapshot_and_idempotency(tmp_path):
 p=plan(tmp_path); m=Ieee8021xManager(); m.apply(p); p.path('supplicant').write_text('old\n'); m.apply(p); assert 'old' in p.path('snapshot').read_text()
def test_rollback(tmp_path):
 p=plan(tmp_path); m=Ieee8021xManager(); m.apply(p); m.rollback(p); assert not p.path('supplicant').exists() and json.loads(p.path('state').read_text())['status']=='rolled-back'
def test_rollback_without_snapshot(tmp_path):
 with pytest.raises(Ieee8021xError,match='snapshot'): Ieee8021xManager().rollback(plan(tmp_path))
def test_dry_run(tmp_path):
 p=plan(tmp_path); paths=Ieee8021xManager().apply(p,dry_run=True); assert not any(x.exists() for x in paths)
def test_cli_options():
 a=build_parser().parse_args(['configure-ieee8021x','--eap','peap','--identity','u','--ca-certificate','/etc/xaac/certificates/ca.pem','--password','x','--dry-run']); assert a.eap=='peap' and a.dry_run
