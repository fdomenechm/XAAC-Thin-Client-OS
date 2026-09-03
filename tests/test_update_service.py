from pathlib import Path
import json
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.update_service import UpdateServiceError, UpdateServiceInstaller, create_update_service_plan, load_update_service
ROOT=Path(__file__).parents[1]
def rootfs(tmp_path):
    p=tmp_path/'.build/rootfs'; p.mkdir(parents=True); return p
def altered(tmp_path,old,new):
    p=tmp_path/'service.yaml'; p.write_text((ROOT/'config/update-service.yaml').read_text().replace(old,new)); return p
def test_loads_service_policy():
    p=load_update_service(ROOT/'config/update-service.yaml'); assert p['schedule']['check_interval_minutes']==60; assert p['storage']['minimum_free_bytes']==536870912
def test_manifest_is_stable(tmp_path):
    plan=create_update_service_plan(rootfs(tmp_path),ROOT/'config/update-service.yaml'); assert plan.manifest()['initial_state']=='idle'
def test_installs_service_timer_state_and_tmpfiles(tmp_path):
    plan=create_update_service_plan(rootfs(tmp_path),ROOT/'config/update-service.yaml'); policy,state,service,timer,tmpfiles=UpdateServiceInstaller().install(plan)
    assert json.loads(state.read_text())['status']=='idle'; assert 'ProtectSystem=strict' in service.read_text(); assert 'Persistent=true' in timer.read_text(); assert '/var/lib/xaac-update/staging' in tmpfiles.read_text(); assert policy.stat().st_mode & 0o777 == 0o640
def test_installation_is_idempotent(tmp_path):
    plan=create_update_service_plan(rootfs(tmp_path),ROOT/'config/update-service.yaml'); i=UpdateServiceInstaller(); paths=i.install(plan); before=[p.read_bytes() for p in paths]; i.install(plan); assert before==[p.read_bytes() for p in paths]
def test_dry_run_does_not_write(tmp_path):
    plan=create_update_service_plan(rootfs(tmp_path),ROOT/'config/update-service.yaml'); paths=UpdateServiceInstaller().install(plan,dry_run=True); assert len(paths)==5 and not any(p.exists() for p in paths)
def test_rejects_small_free_space(tmp_path):
    with pytest.raises(UpdateServiceError,match='minimum_free_bytes'): load_update_service(altered(tmp_path,'536870912','1024'))
def test_rejects_unbounded_interval(tmp_path):
    with pytest.raises(UpdateServiceError,match='check_interval_minutes'): load_update_service(altered(tmp_path,'check_interval_minutes: 60','check_interval_minutes: 1'))
def test_rejects_insecure_path(tmp_path):
    with pytest.raises(UpdateServiceError,match='Ruta insegura'): load_update_service(altered(tmp_path,'/var/lib/xaac-update/staging','../staging'))
def test_rejects_incoherent_state_path(tmp_path):
    with pytest.raises(UpdateServiceError,match='incoherents'): load_update_service(altered(tmp_path,'state: /var/lib/xaac-update/service-state.json','state: /tmp/other.json'))
def test_rejects_symlink_destination(tmp_path):
    plan=create_update_service_plan(rootfs(tmp_path),ROOT/'config/update-service.yaml'); target=plan.output('state'); target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'elsewhere')
    with pytest.raises(UpdateServiceError,match='enllaç simbòlic'): UpdateServiceInstaller().install(plan)
def test_cli_supports_update_service(tmp_path):
    assert build_parser().parse_args(['configure-update-service','--dry-run']).command=='configure-update-service'; rootfs(tmp_path); (tmp_path/'config').mkdir(); (tmp_path/'config/update-service.yaml').write_text((ROOT/'config/update-service.yaml').read_text()); assert main(['--root',str(tmp_path),'configure-update-service','--dry-run'])==0
