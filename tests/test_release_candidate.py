import json
from pathlib import Path
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.release_candidate import (
    ReleaseCandidateBuilder, ReleaseCandidateError, REQUIRED_GATES,
    create_release_candidate_plan, load_release_candidate_profile,
)
ROOT=Path(__file__).resolve().parents[1]
def project(tmp_path):
 p=tmp_path/'p'; (p/'config').mkdir(parents=True); (p/'config/release-candidate.yaml').write_text((ROOT/'config/release-candidate.yaml').read_text()); return p
def test_profile():
 x=load_release_candidate_profile(ROOT/'config/release-candidate.yaml'); assert tuple(x['gates'])==REQUIRED_GATES and x['freeze']['enabled']
def test_manifest():
 x=create_release_candidate_plan(ROOT,ROOT/'config/release-candidate.yaml').manifest(); assert x['version']=='1.1.0-rc.1' and x['status']=='candidate'
def test_prepare(tmp_path):
 p=project(tmp_path); paths=ReleaseCandidateBuilder().prepare(create_release_candidate_plan(p,p/'config/release-candidate.yaml')); assert len(paths)==4; assert json.loads(paths[0].read_text())['frozen']; assert 'pending' in paths[2].read_text()
def test_permissions(tmp_path):
 p=project(tmp_path); paths=ReleaseCandidateBuilder().prepare(create_release_candidate_plan(p,p/'config/release-candidate.yaml')); assert paths[2].stat().st_mode&0o777==0o640; assert paths[3].stat().st_mode&0o777==0o750
def test_idempotent(tmp_path):
 p=project(tmp_path); plan=create_release_candidate_plan(p,p/'config/release-candidate.yaml'); b=ReleaseCandidateBuilder(); before=[x.read_bytes() for x in b.prepare(plan)]; assert before==[x.read_bytes() for x in b.prepare(plan)]
def test_dry_run(tmp_path):
 p=project(tmp_path); paths=ReleaseCandidateBuilder().prepare(create_release_candidate_plan(p,p/'config/release-candidate.yaml'),dry_run=True); assert not any(x.exists() for x in paths)
def test_freeze_required(tmp_path):
 p=project(tmp_path); c=p/'config/release-candidate.yaml'; c.write_text(c.read_text().replace('enabled: true','enabled: false'))
 with pytest.raises(ReleaseCandidateError,match='congelació'): load_release_candidate_profile(c)
def test_missing_gate(tmp_path):
 p=project(tmp_path); c=p/'config/release-candidate.yaml'; c.write_text(c.read_text().replace('  packaging: python -m pytest -q tests/test_production_packaging.py\n',''))
 with pytest.raises(ReleaseCandidateError,match='portes'): load_release_candidate_profile(c)
def test_absolute_artifact(tmp_path):
 p=project(tmp_path); c=p/'config/release-candidate.yaml'; c.write_text(c.read_text().replace('.build/iso/xaac','/tmp/xaac',1))
 with pytest.raises(ReleaseCandidateError,match='relativa'): load_release_candidate_profile(c)
def test_approval_required(tmp_path):
 p=project(tmp_path); c=p/'config/release-candidate.yaml'; c.write_text(c.read_text().replace('required: true','required: false',1))
 with pytest.raises(ReleaseCandidateError,match='aprovació'): load_release_candidate_profile(c)
def test_symlink_output(tmp_path):
 p=project(tmp_path); target=p/'.build/release-candidate/manifest.json'; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'outside')
 with pytest.raises(ReleaseCandidateError,match='enllaç'): ReleaseCandidateBuilder().prepare(create_release_candidate_plan(p,p/'config/release-candidate.yaml'))
def test_cli(tmp_path):
 p=project(tmp_path); assert build_parser().parse_args(['build-release-candidate','--dry-run']).command=='build-release-candidate'; assert main(['--root',str(p),'build-release-candidate','--dry-run'])==0
