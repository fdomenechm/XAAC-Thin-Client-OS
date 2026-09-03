import json
from pathlib import Path
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.documentation import DocumentationBuilder, DocumentationError, REQUIRED, create_documentation_plan, load_documentation_profile
ROOT=Path(__file__).resolve().parents[1]
def project(tmp_path):
 p=tmp_path/'p'; (p/'config').mkdir(parents=True); (p/'docs/manual').mkdir(parents=True)
 (p/'config/documentation.yaml').write_text((ROOT/'config/documentation.yaml').read_text())
 for name in REQUIRED: (p/f'docs/manual/{name}.md').write_text((ROOT/f'docs/manual/{name}.md').read_text())
 return p
def test_load_profile(): assert tuple(load_documentation_profile(ROOT/'config/documentation.yaml')['manuals'])==REQUIRED
def test_manifest_scope(): assert create_documentation_plan(ROOT,ROOT/'config/documentation.yaml').manifest()['manual_count']==8
def test_prepare_assets(tmp_path):
 p=project(tmp_path); plan=create_documentation_plan(p,p/'config/documentation.yaml'); assert len(DocumentationBuilder().prepare(plan))==2; assert json.loads(plan.output('manifest').read_text())['manual_count']==8; assert 'Instal·lació' in plan.output('index').read_text()
def test_permissions(tmp_path):
 p=project(tmp_path); plan=create_documentation_plan(p,p/'config/documentation.yaml'); DocumentationBuilder().prepare(plan); assert plan.output('index').stat().st_mode&0o777==0o644
def test_idempotent(tmp_path):
 p=project(tmp_path); plan=create_documentation_plan(p,p/'config/documentation.yaml'); b=DocumentationBuilder(); b.prepare(plan); before=[x.read_bytes() for x in (plan.output('index'),plan.output('manifest'))]; b.prepare(plan); assert before==[x.read_bytes() for x in (plan.output('index'),plan.output('manifest'))]
def test_dry_run(tmp_path):
 p=project(tmp_path); plan=create_documentation_plan(p,p/'config/documentation.yaml'); paths=DocumentationBuilder().prepare(plan,dry_run=True); assert not any(x.exists() for x in paths)
def test_rejects_missing_manual(tmp_path):
 p=project(tmp_path); (p/'docs/manual/network.md').unlink()
 with pytest.raises(DocumentationError,match='absent'): create_documentation_plan(p,p/'config/documentation.yaml')
def test_rejects_short_manual(tmp_path):
 p=project(tmp_path); (p/'docs/manual/security.md').write_text('# Curt\n')
 with pytest.raises(DocumentationError,match='insuficient'): create_documentation_plan(p,p/'config/documentation.yaml')
def test_rejects_absolute_path(tmp_path):
 p=project(tmp_path); c=p/'config/documentation.yaml'; c.write_text(c.read_text().replace('docs/manual/network.md','/tmp/network.md'))
 with pytest.raises(DocumentationError,match='relativa'): load_documentation_profile(c)
def test_rejects_wrong_order(tmp_path):
 p=project(tmp_path); c=p/'config/documentation.yaml'; text=c.read_text().replace('  installation: docs/manual/installation.md\n  administration: docs/manual/administration.md','  administration: docs/manual/administration.md\n  installation: docs/manual/installation.md'); c.write_text(text)
 with pytest.raises(DocumentationError,match='desordenat'): load_documentation_profile(c)
def test_rejects_symlink_output(tmp_path):
 p=project(tmp_path); target=p/'docs/manual/README.md'; target.symlink_to(tmp_path/'outside')
 with pytest.raises(DocumentationError,match='enllaç'): DocumentationBuilder().prepare(create_documentation_plan(p,p/'config/documentation.yaml'))
def test_cli_dry_run(tmp_path):
 p=project(tmp_path); assert build_parser().parse_args(['build-documentation','--dry-run']).command=='build-documentation'; assert main(['--root',str(p),'build-documentation','--dry-run'])==0
