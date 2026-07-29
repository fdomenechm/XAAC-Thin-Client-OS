from pathlib import Path
import json, stat, pytest
from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.local_admin import *

def profile(tmp_path):
 p=tmp_path/'admin.yaml'; p.write_text(Path('config/local-admin.yaml').read_text()); return p

def plan(tmp_path,**kw):
 return create_local_admin_plan(tmp_path/'rootfs',profile(tmp_path),LocalAdminRequest(**kw))

def test_profile_backend(): assert load_local_admin_profile(Path('config/local-admin.yaml'))['backend']=='systemd-sysusers'
def test_render_account_and_groups(tmp_path):
 p=plan(tmp_path); assert 'u xaac-admin' in p.files['sysusers'] and 'm xaac-admin sudo' in p.files['sysusers']
def test_sudo_is_restricted(tmp_path):
 text=plan(tmp_path).files['sudoers']; assert 'ALL=(root) ALL' not in text and 'xaac-admin-menu' in text and 'use_pty' in text
def test_menu_contains_required_operations(tmp_path):
 text=plan(tmp_path).files['menu']; assert 'networkctl status' in text and 'journalctl' in text and 'passwd' in text
def test_first_login_forces_password_change(tmp_path): assert 'passwd xaac-admin' in plan(tmp_path).files['first_login']
def test_audit_rules(tmp_path): assert 'xaac-admin-command' in plan(tmp_path).files['audit_rules']
def test_rejects_invalid_username(tmp_path):
 with pytest.raises(LocalAdminError,match='fora de política'): plan(tmp_path,username='other')
def test_rejects_invalid_source(tmp_path):
 with pytest.raises(LocalAdminError,match='Font'): plan(tmp_path,source='other')
def test_rejects_bad_password_hash(tmp_path):
 with pytest.raises(LocalAdminError,match='Hash'): plan(tmp_path,password_hash='plain-text')
def test_apply_permissions_and_state(tmp_path):
 p=plan(tmp_path,source='remote',password_hash='$6$salt$hash'); paths=LocalAdminManager().apply(p); assert len(paths)==9
 assert stat.S_IMODE(p.path('sudoers').stat().st_mode)==0o440
 state=json.loads(p.path('state').read_text()); assert state['source']=='remote' and state['password_change_required'] is True and state['audit_enabled'] is True
def test_apply_updates_existing_shadow(tmp_path):
 p=plan(tmp_path,password_hash='$6$salt$hash'); shadow=p.rootfs/'etc/shadow'; shadow.parent.mkdir(parents=True); shadow.write_text('xaac-admin:!:20000:0:99999:7:::\n')
 LocalAdminManager().apply(p); fields=shadow.read_text().strip().split(':'); assert fields[1]=='$6$salt$hash' and fields[2]=='0'
def test_apply_snapshot_and_idempotency(tmp_path):
 p=plan(tmp_path); m=LocalAdminManager(); m.apply(p)
 target=p.path('sudoers'); replacement=target.with_name('.xaac-admin.test-replacement')
 replacement.write_text('old\n',encoding='utf-8'); replacement.chmod(0o440); replacement.replace(target)
 m.apply(p); assert 'old' in p.path('snapshot').read_text()
def test_rollback(tmp_path):
 p=plan(tmp_path); m=LocalAdminManager(); m.apply(p); m.rollback(p); assert not p.path('sudoers').exists() and json.loads(p.path('state').read_text())['status']=='rolled-back'
def test_rollback_without_snapshot(tmp_path):
 with pytest.raises(LocalAdminError,match='snapshot'): LocalAdminManager().rollback(plan(tmp_path))
def test_dry_run(tmp_path):
 p=plan(tmp_path); paths=LocalAdminManager().apply(p,dry_run=True); assert not any(x.exists() for x in paths)
def test_symlink_protection(tmp_path):
 p=plan(tmp_path); target=p.path('sudoers'); target.parent.mkdir(parents=True); outside=tmp_path/'outside'; outside.write_text('safe'); target.symlink_to(outside)
 with pytest.raises(LocalAdminError,match='enllaç simbòlic'): LocalAdminManager().apply(p)
def test_cli_options():
 a=build_parser().parse_args(['configure-local-admin','--source','remote','--password-hash','$6$s$h','--dry-run']); assert a.source=='remote' and a.dry_run
