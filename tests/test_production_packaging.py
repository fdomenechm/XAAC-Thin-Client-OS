import json
from pathlib import Path
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.production_packaging import ProductionPackagingBuilder, ProductionPackagingError, REQUIRED_CHANNELS, REQUIRED_PACKAGES, create_production_packaging_plan, load_production_packaging_profile
ROOT=Path(__file__).resolve().parents[1]
def project(tmp_path):
 p=tmp_path/'p'; (p/'config').mkdir(parents=True); (p/'config/production-packaging.yaml').write_text((ROOT/'config/production-packaging.yaml').read_text())
 for name in REQUIRED_PACKAGES: (p/f'packaging/{name}').mkdir(parents=True)
 return p
def test_profile():
 x=load_production_packaging_profile(ROOT/'config/production-packaging.yaml'); assert tuple(x['channels'])==REQUIRED_CHANNELS
def test_manifest(): assert create_production_packaging_plan(ROOT,ROOT/'config/production-packaging.yaml').manifest()['metapackage']=='xaac-thin-client-os'
def test_prepare(tmp_path):
 p=project(tmp_path); plan=create_production_packaging_plan(p,p/'config/production-packaging.yaml'); paths=ProductionPackagingBuilder().prepare(plan); assert len(paths)==3; assert json.loads(paths[0].read_text())['signed']; assert 'reprepro' in paths[1].read_text()
def test_permissions(tmp_path):
 p=project(tmp_path); plan=create_production_packaging_plan(p,p/'config/production-packaging.yaml'); paths=ProductionPackagingBuilder().prepare(plan); assert paths[1].stat().st_mode&0o777==0o750
def test_idempotent(tmp_path):
 p=project(tmp_path); plan=create_production_packaging_plan(p,p/'config/production-packaging.yaml'); b=ProductionPackagingBuilder(); b.prepare(plan); before=[x.read_bytes() for x in b.prepare(plan)]; assert before==[x.read_bytes() for x in b.prepare(plan)]
def test_dry_run(tmp_path):
 p=project(tmp_path); plan=create_production_packaging_plan(p,p/'config/production-packaging.yaml'); paths=ProductionPackagingBuilder().prepare(plan,dry_run=True); assert not any(x.exists() for x in paths)
def test_missing_source(tmp_path):
 p=project(tmp_path); (p/'packaging/xaac-agent').rmdir()
 with pytest.raises(ProductionPackagingError,match='absent'): create_production_packaging_plan(p,p/'config/production-packaging.yaml')
def test_absolute_path(tmp_path):
 p=project(tmp_path); c=p/'config/production-packaging.yaml'; c.write_text(c.read_text().replace('packaging/xaac-agent','/tmp/agent'))
 with pytest.raises(ProductionPackagingError,match='relativa'): load_production_packaging_profile(c)
def test_bad_channels(tmp_path):
 p=project(tmp_path); c=p/'config/production-packaging.yaml'; c.write_text(c.read_text().replace('  pilot: pilot\n',''))
 with pytest.raises(ProductionPackagingError,match='Canals'): load_production_packaging_profile(c)
def test_signing_required(tmp_path):
 p=project(tmp_path); c=p/'config/production-packaging.yaml'; c.write_text(c.read_text().replace('required: true','required: false'))
 with pytest.raises(ProductionPackagingError,match='signatura'): load_production_packaging_profile(c)
def test_symlink_output(tmp_path):
 p=project(tmp_path); target=p/'.build/packaging/manifest.json'; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'outside')
 with pytest.raises(ProductionPackagingError,match='enllaç'): ProductionPackagingBuilder().prepare(create_production_packaging_plan(p,p/'config/production-packaging.yaml'))
def test_cli(tmp_path):
 p=project(tmp_path); assert build_parser().parse_args(['build-production-packaging','--dry-run']).command=='build-production-packaging'; assert main(['--root',str(p),'build-production-packaging','--dry-run'])==0
