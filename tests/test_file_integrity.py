from __future__ import annotations
import json
from pathlib import Path
import pytest, yaml
from xaac_thin_client_os.file_integrity import FileIntegrityError, FileIntegrityManager, create_file_integrity_plan, load_file_integrity_policy
from xaac_thin_client_os.cli import build_parser, main
PROFILE=Path('config/file-integrity.yaml')

def rootfs(tmp_path):
    r=tmp_path/'rootfs'; (r/'etc/xaac').mkdir(parents=True); (r/'etc/xaac/config.json').write_text('{"ok":true}\n'); return r

def test_policy_loads():
    p=load_file_integrity_policy(PROFILE); assert p['algorithm']=='sha256' and '/etc/xaac' in p['monitored_paths']

def test_unsafe_root_rejected(tmp_path):
    with pytest.raises(FileIntegrityError,match='Rootfs insegur'): create_file_integrity_plan(tmp_path,PROFILE)

def test_duplicate_paths_rejected(tmp_path):
    d=yaml.safe_load(PROFILE.read_text()); d['monitored_paths'].append(d['monitored_paths'][0]); f=tmp_path/'p.yaml'; f.write_text(yaml.safe_dump(d))
    with pytest.raises(FileIntegrityError,match='duplicades'):load_file_integrity_policy(f)

def test_unsafe_output_rejected(tmp_path):
    d=yaml.safe_load(PROFILE.read_text()); d['outputs']['manifest']='/var/../etc/x'; f=tmp_path/'p.yaml'; f.write_text(yaml.safe_dump(d))
    with pytest.raises(FileIntegrityError,match='Ruta insegura'):load_file_integrity_policy(f)

def test_install_builds_manifest_and_baseline(tmp_path):
    plan=create_file_integrity_plan(rootfs(tmp_path),PROFILE); paths=FileIntegrityManager().install(plan); assert len(paths)==6
    m=json.loads(plan.output('manifest').read_text()); assert m['files'][0]['path']=='/etc/xaac/config.json' and len(m['files'][0]['sha256'])==64
    assert (plan.destination(plan.profile['repair']['baseline_dir'])/'etc/xaac/config.json').is_file()
    assert plan.output('verifier').stat().st_mode & 0o777==0o750

def test_verify_detects_and_repairs(tmp_path):
    plan=create_file_integrity_plan(rootfs(tmp_path),PROFILE); mgr=FileIntegrityManager(); mgr.install(plan)
    target=plan.destination('/etc/xaac/config.json'); target.write_text('tampered')
    result=mgr.verify(plan); assert result['status']=='alert' and result['changed']==['/etc/xaac/config.json']
    result=mgr.verify(plan,repair=True); assert result['status']=='repaired' and json.loads(target.read_text())['ok'] is True

def test_missing_file_detected(tmp_path):
    plan=create_file_integrity_plan(rootfs(tmp_path),PROFILE); mgr=FileIntegrityManager(); mgr.install(plan); plan.destination('/etc/xaac/config.json').unlink(); assert mgr.verify(plan)['status']=='alert'

def test_install_idempotent(tmp_path):
    plan=create_file_integrity_plan(rootfs(tmp_path),PROFILE); mgr=FileIntegrityManager(); mgr.install(plan); before=plan.output('manifest').read_bytes(); mgr.install(plan); assert before==plan.output('manifest').read_bytes()

def test_symlink_destination_rejected(tmp_path):
    plan=create_file_integrity_plan(rootfs(tmp_path),PROFILE); t=plan.output('manifest'); t.parent.mkdir(parents=True); t.symlink_to(tmp_path/'x')
    with pytest.raises(FileIntegrityError,match='enllaç simbòlic'):FileIntegrityManager().install(plan)

def test_dry_run(tmp_path):
    plan=create_file_integrity_plan(rootfs(tmp_path),PROFILE); paths=FileIntegrityManager().install(plan,dry_run=True); assert all(not p.exists() for p in paths)

def test_cli_commands(tmp_path):
    assert build_parser().parse_args(['configure-file-integrity','--dry-run']).command=='configure-file-integrity'
    assert build_parser().parse_args(['verify-file-integrity','--repair']).repair is True
    root=tmp_path/'project'; (root/'config').mkdir(parents=True); (root/'config/file-integrity.yaml').write_bytes(PROFILE.read_bytes())
    assert main(['--root',str(root),'configure-file-integrity','--dry-run'])==0
