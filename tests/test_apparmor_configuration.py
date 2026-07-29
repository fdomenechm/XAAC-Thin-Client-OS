from __future__ import annotations
import json, os
from pathlib import Path
import pytest, yaml
from xaac_thin_client_os.apparmor_configuration import AppArmorError, AppArmorInstaller, create_apparmor_plan, load_apparmor_policy
from xaac_thin_client_os.cli import build_parser, main
PROFILE=Path('config/apparmor.yaml')

def test_profile_loads_and_covers_modes():
    p=load_apparmor_policy(PROFILE)
    assert len(p['profiles'])==3
    assert {x['mode'] for x in p['profiles']}=={'enforce','complain'}
    assert p['defaults']['audit_denied'] is True

def test_unsafe_rootfs_rejected(tmp_path):
    with pytest.raises(AppArmorError,match='Rootfs insegur'): create_apparmor_plan(tmp_path,PROFILE)

def test_duplicate_profile_rejected(tmp_path):
    d=yaml.safe_load(PROFILE.read_text()); d['profiles'].append(dict(d['profiles'][0])); f=tmp_path/'p.yaml'; f.write_text(yaml.safe_dump(d))
    with pytest.raises(AppArmorError,match='duplicat'): load_apparmor_policy(f)

def test_unsafe_path_rejected(tmp_path):
    d=yaml.safe_load(PROFILE.read_text()); d['profiles'][0]['write_paths']=['/var/lib/../etc/**']; f=tmp_path/'p.yaml'; f.write_text(yaml.safe_dump(d))
    with pytest.raises(AppArmorError,match='Ruta insegura'): load_apparmor_policy(f)

def test_invalid_mode_rejected(tmp_path):
    d=yaml.safe_load(PROFILE.read_text()); d['profiles'][0]['mode']='disabled'; f=tmp_path/'p.yaml'; f.write_text(yaml.safe_dump(d))
    with pytest.raises(AppArmorError,match='Mode AppArmor'): load_apparmor_policy(f)

def test_install_writes_profiles_links_and_state(tmp_path):
    plan=create_apparmor_plan(tmp_path/'rootfs',PROFILE); paths=AppArmorInstaller().install(plan)
    assert len(paths)==6
    agent=plan.profile_path('usr.sbin.xaac-agent').read_text()
    assert 'profile usr.sbin.xaac-agent /usr/sbin/xaac-agent' in agent
    assert 'capability net_admin,' in agent
    link=plan.complain_link('usr.bin.xaac-rustdesk')
    assert link.is_symlink() and os.readlink(link)=='../usr.bin.xaac-rustdesk'
    state=json.loads(plan.destination('state').read_text())
    assert state['enforce_count']==2 and state['complain_count']==1

def test_enforce_profile_has_no_complain_link(tmp_path):
    plan=create_apparmor_plan(tmp_path/'rootfs',PROFILE); AppArmorInstaller().install(plan)
    assert not plan.complain_link('usr.sbin.xaac-agent').exists()

def test_install_idempotent(tmp_path):
    plan=create_apparmor_plan(tmp_path/'rootfs',PROFILE); i=AppArmorInstaller(); i.install(plan)
    before={p:(p.readlink() if p.is_symlink() else p.read_bytes()) for p in i.install(plan,dry_run=True)}
    i.install(plan)
    after={p:(p.readlink() if p.is_symlink() else p.read_bytes()) for p in before}
    assert before==after

def test_symlink_destination_rejected(tmp_path):
    plan=create_apparmor_plan(tmp_path/'rootfs',PROFILE); t=plan.destination('policy'); t.parent.mkdir(parents=True); t.symlink_to(tmp_path/'elsewhere')
    with pytest.raises(AppArmorError,match='enllaç simbòlic'): AppArmorInstaller().install(plan)

def test_dry_run_does_not_write(tmp_path):
    plan=create_apparmor_plan(tmp_path/'rootfs',PROFILE); paths=AppArmorInstaller().install(plan,dry_run=True)
    assert all(not p.exists() for p in paths)

def test_cli_exposes_apparmor(tmp_path):
    assert build_parser().parse_args(['configure-apparmor','--dry-run']).command=='configure-apparmor'
    root=tmp_path/'project'; (root/'config').mkdir(parents=True); (root/'config/apparmor.yaml').write_bytes(PROFILE.read_bytes())
    assert main(['--root',str(root),'configure-apparmor','--dry-run'])==0
