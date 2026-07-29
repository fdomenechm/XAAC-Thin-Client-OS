from pathlib import Path
import json, pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.transactional_update import TransactionalUpdateError, TransactionalUpdateInstaller, create_transactional_update_plan, load_transactional_update
ROOT=Path(__file__).parents[1]
def rootfs(tmp_path):
    p=tmp_path/'.build/rootfs';p.mkdir(parents=True);return p
def altered(tmp_path,old,new):
    p=tmp_path/'transaction.yaml';p.write_text((ROOT/'config/transactional-update.yaml').read_text().replace(old,new));return p
def test_loads_transactional_policy():
    p=load_transactional_update(ROOT/'config/transactional-update.yaml');assert p['failure']['automatic_rollback'] is True
def test_manifest_is_stable(tmp_path):
    assert create_transactional_update_plan(rootfs(tmp_path),ROOT/'config/transactional-update.yaml').manifest()['hardware_profile']=='wyse3040'
def test_installs_policy_state_launcher_and_service(tmp_path):
    p,s,l,u=TransactionalUpdateInstaller().install(create_transactional_update_plan(rootfs(tmp_path),ROOT/'config/transactional-update.yaml'));assert json.loads(s.read_text())['status']=='idle';assert 'install-verified' in l.read_text();assert 'ProtectSystem=strict' in u.read_text();assert p.stat().st_mode&0o777==0o640

def test_installation_is_idempotent(tmp_path):
    plan=create_transactional_update_plan(rootfs(tmp_path),ROOT/'config/transactional-update.yaml');i=TransactionalUpdateInstaller();paths=i.install(plan);before=[p.read_bytes() for p in paths];i.install(plan);assert before==[p.read_bytes() for p in paths]
def test_dry_run_does_not_write(tmp_path):
    paths=TransactionalUpdateInstaller().install(create_transactional_update_plan(rootfs(tmp_path),ROOT/'config/transactional-update.yaml'),dry_run=True);assert len(paths)==4 and not any(p.exists() for p in paths)
def test_rejects_optional_recovery_point(tmp_path):
    with pytest.raises(TransactionalUpdateError,match='recuperació'):load_transactional_update(altered(tmp_path,'required: true','required: false'))
def test_rejects_unverified_staging(tmp_path):
    with pytest.raises(TransactionalUpdateError,match='Instal·lació'):load_transactional_update(altered(tmp_path,'require_verified_staging: true','require_verified_staging: false'))
def test_rejects_non_fail_closed_validation(tmp_path):
    with pytest.raises(TransactionalUpdateError,match='Validació'):load_transactional_update(altered(tmp_path,'fail_closed: true','fail_closed: false'))
def test_rejects_disabled_rollback(tmp_path):
    with pytest.raises(TransactionalUpdateError,match='fallada'):load_transactional_update(altered(tmp_path,'automatic_rollback: true','automatic_rollback: false'))
def test_rejects_insecure_path(tmp_path):
    with pytest.raises(TransactionalUpdateError,match='Ruta insegura'):load_transactional_update(altered(tmp_path,'/var/lib/xaac-update/recovery-points','../recovery'))
def test_rejects_symlink_destination(tmp_path):
    plan=create_transactional_update_plan(rootfs(tmp_path),ROOT/'config/transactional-update.yaml');target=plan.output('state');target.parent.mkdir(parents=True);target.symlink_to(tmp_path/'elsewhere')
    with pytest.raises(TransactionalUpdateError,match='enllaç simbòlic'):TransactionalUpdateInstaller().install(plan)
def test_cli_supports_transactional_update(tmp_path):
    assert build_parser().parse_args(['configure-transactional-update','--dry-run']).command=='configure-transactional-update';rootfs(tmp_path);(tmp_path/'config').mkdir();(tmp_path/'config/transactional-update.yaml').write_text((ROOT/'config/transactional-update.yaml').read_text());assert main(['--root',str(tmp_path),'configure-transactional-update','--dry-run'])==0
