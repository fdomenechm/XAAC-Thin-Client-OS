import json
from pathlib import Path
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.hardware_final_tests import HardwareFinalTestsBuilder, HardwareFinalTestsError, create_hardware_final_tests_plan, load_hardware_final_tests

ROOT=Path(__file__).resolve().parents[1]

def copied(tmp_path, old, new):
    path=tmp_path/'p.yaml'; path.write_text((ROOT/'config/hardware-final-tests.yaml').read_text().replace(old,new)); return path

def test_load_profile():
    p=load_hardware_final_tests(ROOT/'config/hardware-final-tests.yaml'); assert list(p['categories'])[0]=='installation'

def test_manifest_covers_final_scope():
    m=create_hardware_final_tests_plan(ROOT,ROOT/'config/hardware-final-tests.yaml').manifest(); assert m['categories'][-1]=='recovery' and m['check_count']>=18

def test_prepare_assets(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/hardware-final-tests.yaml').read_text()); plan=create_hardware_final_tests_plan(p,c); assert len(HardwareFinalTestsBuilder().prepare(plan))==4; assert json.loads(plan.output('manifest').read_text())['require_real_hardware'] is True; assert 'dmidecode' in plan.output('runner').read_text()

def test_runner_permissions(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/hardware-final-tests.yaml').read_text()); plan=create_hardware_final_tests_plan(p,c); HardwareFinalTestsBuilder().prepare(plan); assert plan.output('runner').stat().st_mode & 0o777 == 0o750

def test_idempotent(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/hardware-final-tests.yaml').read_text()); plan=create_hardware_final_tests_plan(p,c); b=HardwareFinalTestsBuilder(); b.prepare(plan); before=[x.read_bytes() for x in (plan.output('manifest'),plan.output('runner'),plan.output('checklist'))]; b.prepare(plan); assert before==[x.read_bytes() for x in (plan.output('manifest'),plan.output('runner'),plan.output('checklist'))]

def test_dry_run(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/hardware-final-tests.yaml').read_text()); paths=HardwareFinalTestsBuilder().prepare(create_hardware_final_tests_plan(p,c),dry_run=True); assert len(paths)==4 and not any(x.exists() for x in paths)

def test_requires_real_hardware(tmp_path):
    with pytest.raises(HardwareFinalTestsError,match='maquinari real'): load_hardware_final_tests(copied(tmp_path,'require_real_hardware: true','require_real_hardware: false'))

def test_rejects_missing_category(tmp_path):
    with pytest.raises(HardwareFinalTestsError,match='Categories'): load_hardware_final_tests(copied(tmp_path,'  recovery:\n    enabled: true','  recovery-disabled:\n    enabled: true'))

def test_rejects_disabled_category(tmp_path):
    with pytest.raises(HardwareFinalTestsError,match='rdp'): load_hardware_final_tests(copied(tmp_path,'  rdp:\n    enabled: true','  rdp:\n    enabled: false'))

def test_rejects_duration(tmp_path):
    with pytest.raises(HardwareFinalTestsError,match='Duració'): load_hardware_final_tests(copied(tmp_path,'continuous_use_hours: 24','continuous_use_hours: 0'))

def test_rejects_symlink(tmp_path):
    p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/hardware-final-tests.yaml').read_text()); target=p/'.build/hardware-final-tests/manifest.json'; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'outside');
    with pytest.raises(HardwareFinalTestsError,match='enllaç'): HardwareFinalTestsBuilder().prepare(create_hardware_final_tests_plan(p,c))

def test_cli_dry_run(tmp_path):
    assert build_parser().parse_args(['build-hardware-tests','--dry-run']).command=='build-hardware-tests'; (tmp_path/'config').mkdir(); (tmp_path/'config/hardware-final-tests.yaml').write_text((ROOT/'config/hardware-final-tests.yaml').read_text()); assert main(['--root',str(tmp_path),'build-hardware-tests','--dry-run'])==0
