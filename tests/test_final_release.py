import json
from pathlib import Path
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.final_release import (
    FinalReleaseBuilder, FinalReleaseError, REQUIRED_ARTIFACTS,
    create_final_release_plan, load_final_release_profile,
)
ROOT=Path(__file__).resolve().parents[1]
def project(tmp_path):
 p=tmp_path/'p'; (p/'config').mkdir(parents=True); (p/'config/final-release.yaml').write_text((ROOT/'config/final-release.yaml').read_text()); (p/'VERSION').write_text('1.1.0\n'); return p
def test_profile():
 x=load_final_release_profile(ROOT/'config/final-release.yaml'); assert tuple(x['artifacts'])==REQUIRED_ARTIFACTS and x['version']=='1.1.0'
def test_manifest():
 x=create_final_release_plan(ROOT,ROOT/'config/final-release.yaml').manifest(); assert x['status']=='stable' and x['documentation_included']
def test_prepare(tmp_path):
 p=project(tmp_path); paths=FinalReleaseBuilder().prepare(create_final_release_plan(p,p/'config/final-release.yaml')); assert len(paths)==5; assert json.loads(paths[0].read_text())['version']=='1.1.0'; assert 'SHA256SUMS' in paths[3].read_text()
def test_permissions(tmp_path):
 p=project(tmp_path); paths=FinalReleaseBuilder().prepare(create_final_release_plan(p,p/'config/final-release.yaml')); assert paths[3].stat().st_mode&0o777==0o750; assert paths[4].stat().st_mode&0o777==0o750
def test_idempotent(tmp_path):
 p=project(tmp_path); plan=create_final_release_plan(p,p/'config/final-release.yaml'); b=FinalReleaseBuilder(); before=[x.read_bytes() for x in b.prepare(plan)]; assert before==[x.read_bytes() for x in b.prepare(plan)]
def test_dry_run(tmp_path):
 p=project(tmp_path); paths=FinalReleaseBuilder().prepare(create_final_release_plan(p,p/'config/final-release.yaml'),dry_run=True); assert not any(x.exists() for x in paths)
def test_wrong_version(tmp_path):
 p=project(tmp_path); c=p/'config/final-release.yaml'; c.write_text(c.read_text().replace('version: 1.1.0','version: 1.0.1'))
 with pytest.raises(FinalReleaseError,match='versió'): load_final_release_profile(c)
def test_missing_artifact(tmp_path):
 p=project(tmp_path); c=p/'config/final-release.yaml'; c.write_text(c.read_text().replace('  documentation: docs/manual\n',''))
 with pytest.raises(FinalReleaseError,match='artefactes'): load_final_release_profile(c)
def test_absolute_artifact(tmp_path):
 p=project(tmp_path); c=p/'config/final-release.yaml'; c.write_text(c.read_text().replace('.build/iso/xaac','/tmp/xaac',1))
 with pytest.raises(FinalReleaseError,match='relativa'): load_final_release_profile(c)
def test_signatures_required(tmp_path):
 p=project(tmp_path); c=p/'config/final-release.yaml'; c.write_text(c.read_text().replace('detached_signatures: true','detached_signatures: false'))
 with pytest.raises(FinalReleaseError,match='signatures'): load_final_release_profile(c)
def test_symlink_output(tmp_path):
 p=project(tmp_path); target=p/'.build/final-release/manifest.json'; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'outside')
 with pytest.raises(FinalReleaseError,match='enllaç'): create_final_release_plan(p,p/'config/final-release.yaml')
def test_cli(tmp_path):
 p=project(tmp_path); assert build_parser().parse_args(['build-final-release','--dry-run']).command=='build-final-release'; assert main(['--root',str(p),'build-final-release','--dry-run'])==0
