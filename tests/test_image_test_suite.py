import json
from pathlib import Path
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.image_test_suite import ImageTestSuiteBuilder, ImageTestSuiteError, create_image_test_suite_plan, load_image_test_suite
ROOT=Path(__file__).parents[1]
def copied(tmp_path, old, new):
    p=tmp_path/'image-tests.yaml'; p.write_text((ROOT/'config/image-tests.yaml').read_text().replace(old,new)); return p
def test_loads_policy():
    p=load_image_test_suite(ROOT/'config/image-tests.yaml'); assert list(p['categories'])[0]=='boot'
def test_manifest_is_stable():
    m=create_image_test_suite_plan(ROOT,ROOT/'config/image-tests.yaml').manifest(); assert m['categories'][-1]=='recovery' and m['check_count']>=20
def test_prepares_assets(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/image-tests.yaml').read_text()); plan=create_image_test_suite_plan(p,c); assert len(ImageTestSuiteBuilder().prepare(plan))==3; assert json.loads(plan.output('manifest').read_text())['fail_fast'] is False; assert 'systemctl is-system-running' in plan.output('runner').read_text()
def test_runner_is_executable(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/image-tests.yaml').read_text()); plan=create_image_test_suite_plan(p,c); ImageTestSuiteBuilder().prepare(plan); assert plan.output('runner').stat().st_mode & 0o777 == 0o750
def test_idempotent(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/image-tests.yaml').read_text()); plan=create_image_test_suite_plan(p,c); b=ImageTestSuiteBuilder(); b.prepare(plan); before=[x.read_bytes() for x in (plan.output('manifest'),plan.output('runner'))]; b.prepare(plan); assert before==[x.read_bytes() for x in (plan.output('manifest'),plan.output('runner'))]
def test_dry_run(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/image-tests.yaml').read_text()); paths=ImageTestSuiteBuilder().prepare(create_image_test_suite_plan(p,c),dry_run=True); assert len(paths)==3 and not any(x.exists() for x in paths)
def test_rejects_missing_category(tmp_path):
    with pytest.raises(ImageTestSuiteError,match='Categories'): load_image_test_suite(copied(tmp_path,'  recovery:\n    enabled: true','  recovery-disabled:\n    enabled: true'))
def test_rejects_disabled_category(tmp_path):
    with pytest.raises(ImageTestSuiteError,match='boot'): load_image_test_suite(copied(tmp_path,'  boot:\n    enabled: true','  boot:\n    enabled: false'))
def test_rejects_fail_fast(tmp_path):
    with pytest.raises(ImageTestSuiteError,match="totes"): load_image_test_suite(copied(tmp_path,'fail_fast: false','fail_fast: true'))
def test_rejects_bad_timeout(tmp_path):
    with pytest.raises(ImageTestSuiteError,match='Timeout'): load_image_test_suite(copied(tmp_path,'timeout_seconds: 900','timeout_seconds: 10'))
def test_rejects_symlink(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/image-tests.yaml').read_text()); target=p/'.build/image-tests/manifest.json'; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'outside');
    with pytest.raises(ImageTestSuiteError,match='enllaç'): ImageTestSuiteBuilder().prepare(create_image_test_suite_plan(p,c))
def test_cli(tmp_path):
    assert build_parser().parse_args(['build-image-tests','--dry-run']).command=='build-image-tests'; (tmp_path/'config').mkdir(); (tmp_path/'config/image-tests.yaml').write_text((ROOT/'config/image-tests.yaml').read_text()); assert main(['--root',str(tmp_path),'build-image-tests','--dry-run'])==0
