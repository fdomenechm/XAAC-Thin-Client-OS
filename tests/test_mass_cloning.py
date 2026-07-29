import json
from pathlib import Path
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.mass_cloning import MassCloningBuilder, MassCloningError, create_mass_cloning_plan, load_mass_cloning
ROOT = Path(__file__).parents[1]
def copied(tmp_path, old, new):
    path=tmp_path/'mass-cloning.yaml'; path.write_text((ROOT/'config/mass-cloning.yaml').read_text().replace(old,new)); return path
def test_loads_policy():
    p=load_mass_cloning(ROOT/'config/mass-cloning.yaml'); assert p['deployment']['parallel_jobs']==4
def test_manifest_is_stable():
    m=create_mass_cloning_plan(ROOT,ROOT/'config/mass-cloning.yaml').manifest(); assert m['steps'][0]=='verify-master' and m['confirmation_phrase']=='CLONE XAAC'
def test_prepares_assets(tmp_path):
    project=tmp_path/'p'; project.mkdir(); cfg=project/'c'; cfg.write_text((ROOT/'config/mass-cloning.yaml').read_text()); plan=create_mass_cloning_plan(project,cfg); assert len(MassCloningBuilder().prepare(plan))==4; assert json.loads(plan.output('manifest').read_text())['parallel_jobs']==4; assert 'remove_xaac' not in plan.output('sanitize_script').read_text(); assert 'xaac-first-boot.pending' in plan.output('sanitize_script').read_text(); assert 'cmp -n' in plan.output('clone_script').read_text()
def test_scripts_are_executable(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/mass-cloning.yaml').read_text()); plan=create_mass_cloning_plan(p,c); MassCloningBuilder().prepare(plan); assert all(plan.output(k).stat().st_mode & 0o777 == 0o750 for k in ('sanitize_script','clone_script','verify_script'))
def test_idempotent(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/mass-cloning.yaml').read_text()); plan=create_mass_cloning_plan(p,c); b=MassCloningBuilder(); b.prepare(plan); before=[x.read_bytes() for x in (plan.output('manifest'),plan.output('clone_script'))]; b.prepare(plan); assert before==[x.read_bytes() for x in (plan.output('manifest'),plan.output('clone_script'))]
def test_dry_run(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/mass-cloning.yaml').read_text()); paths=MassCloningBuilder().prepare(create_mass_cloning_plan(p,c),dry_run=True); assert len(paths)==4 and not any(x.exists() for x in paths)
def test_rejects_checksum_disabled(tmp_path):
    with pytest.raises(MassCloningError,match='SHA-256'): load_mass_cloning(copied(tmp_path,'verify_sha256: true','verify_sha256: false'))
def test_rejects_incomplete_sanitization(tmp_path):
    with pytest.raises(MassCloningError,match='Sanejament'): load_mass_cloning(copied(tmp_path,'remove_machine_id: true','remove_machine_id: false'))
def test_rejects_identity_regeneration_disabled(tmp_path):
    with pytest.raises(MassCloningError,match="identitat"): load_mass_cloning(copied(tmp_path,'regenerate_xaac_identity: true','regenerate_xaac_identity: false'))
def test_rejects_bad_parallel_jobs(tmp_path):
    with pytest.raises(MassCloningError,match='paral·lels'): load_mass_cloning(copied(tmp_path,'parallel_jobs: 4','parallel_jobs: 0'))
def test_rejects_symlink(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/mass-cloning.yaml').read_text()); target=p/'.build/cloning/manifest.json'; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'outside');
    with pytest.raises(MassCloningError,match='enllaç'): MassCloningBuilder().prepare(create_mass_cloning_plan(p,c))
def test_cli(tmp_path):
    assert build_parser().parse_args(['build-cloning','--dry-run']).command=='build-cloning'; (tmp_path/'config').mkdir(); (tmp_path/'config/mass-cloning.yaml').write_text((ROOT/'config/mass-cloning.yaml').read_text()); assert main(['--root',str(tmp_path),'build-cloning','--dry-run'])==0
