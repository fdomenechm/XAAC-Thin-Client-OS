import json
from pathlib import Path
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.performance_stability import PerformanceStabilityBuilder, PerformanceStabilityError, create_performance_stability_plan, load_performance_stability
ROOT=Path(__file__).resolve().parents[1]
def copied(tmp_path,old,new):
 p=tmp_path/'p.yaml'; p.write_text((ROOT/'config/performance-stability.yaml').read_text().replace(old,new)); return p
def test_load_profile(): assert list(load_performance_stability(ROOT/'config/performance-stability.yaml')['metrics'])[-1]=='intermittent_network'
def test_manifest_scope():
 m=create_performance_stability_plan(ROOT,ROOT/'config/performance-stability.yaml').manifest(); assert m['metric_count']==7 and m['long_session_hours']==24
def test_prepare_assets(tmp_path):
 p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/performance-stability.yaml').read_text()); plan=create_performance_stability_plan(p,c); assert len(PerformanceStabilityBuilder().prepare(plan))==4; assert json.loads(plan.output('manifest').read_text())['metric_count']==7; assert 'systemd-analyze' in plan.output('runner').read_text()
def test_runner_permissions(tmp_path):
 p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/performance-stability.yaml').read_text()); plan=create_performance_stability_plan(p,c); PerformanceStabilityBuilder().prepare(plan); assert plan.output('runner').stat().st_mode & 0o777==0o750
def test_idempotent(tmp_path):
 p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/performance-stability.yaml').read_text()); plan=create_performance_stability_plan(p,c); b=PerformanceStabilityBuilder(); b.prepare(plan); before=[x.read_bytes() for x in (plan.output('manifest'),plan.output('runner'))]; b.prepare(plan); assert before==[x.read_bytes() for x in (plan.output('manifest'),plan.output('runner'))]
def test_dry_run(tmp_path):
 p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/performance-stability.yaml').read_text()); paths=PerformanceStabilityBuilder().prepare(create_performance_stability_plan(p,c),dry_run=True); assert len(paths)==4 and not any(x.exists() for x in paths)
def test_rejects_missing_metric(tmp_path):
 with pytest.raises(PerformanceStabilityError,match='Mètriques'): load_performance_stability(copied(tmp_path,'  intermittent_network:','  intermittent_network_disabled:'))
def test_rejects_disabled_metric(tmp_path):
 with pytest.raises(PerformanceStabilityError,match='cpu'): load_performance_stability(copied(tmp_path,'  cpu:\n    enabled: true','  cpu:\n    enabled: false'))
def test_rejects_threshold(tmp_path):
 with pytest.raises(PerformanceStabilityError,match='Llindar'): load_performance_stability(copied(tmp_path,'    threshold: 45','    threshold: 0'))
def test_rejects_duration(tmp_path):
 with pytest.raises(PerformanceStabilityError,match='Duració'): load_performance_stability(copied(tmp_path,'long_session_hours: 24','long_session_hours: 0'))
def test_rejects_symlink(tmp_path):
 p=tmp_path/'p'; p.mkdir(); c=p/'c'; c.write_text((ROOT/'config/performance-stability.yaml').read_text()); target=p/'.build/performance-stability/manifest.json'; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'outside');
 with pytest.raises(PerformanceStabilityError,match='enllaç'): PerformanceStabilityBuilder().prepare(create_performance_stability_plan(p,c))
def test_cli_dry_run(tmp_path):
 assert build_parser().parse_args(['build-performance-tests','--dry-run']).command=='build-performance-tests'; (tmp_path/'config').mkdir(); (tmp_path/'config/performance-stability.yaml').write_text((ROOT/'config/performance-stability.yaml').read_text()); assert main(['--root',str(tmp_path),'build-performance-tests','--dry-run'])==0
