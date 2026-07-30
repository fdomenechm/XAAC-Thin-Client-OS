from pathlib import Path
import json, pytest
from xaac_thin_client_os.factory_reset import FactoryResetError, FactoryResetInstaller, create_factory_reset_plan, load_factory_reset
from xaac_thin_client_os.cli import build_parser, main
ROOT=Path(__file__).parents[1]
def rootfs(tmp_path):
 p=tmp_path/".build/rootfs";p.mkdir(parents=True);return p
def altered(tmp_path,old,new):
 p=tmp_path/"factory-reset.yaml";p.write_text((ROOT/"config/factory-reset.yaml").read_text().replace(old,new));return p
def test_loads_factory_reset():
 p=load_factory_reset(ROOT/"config/factory-reset.yaml");assert p["confirmation"]["require_physical_presence"] is True and p["safety"]["automatic_reset"] is False
def test_manifest_is_stable(tmp_path):
 assert create_factory_reset_plan(rootfs(tmp_path),ROOT/"config/factory-reset.yaml").manifest()=={"schema_version":1,"reset_id":"xaac-factory-reset-1","preserved_items":4,"removed_items":5,"restore_source":"recovery_partition","automatic_reset":False}
def test_installs_factory_reset_assets(tmp_path):
 paths=FactoryResetInstaller().install(create_factory_reset_plan(rootfs(tmp_path),ROOT/"config/factory-reset.yaml"));policy,state,service,first_service,runner,first_runner=paths
 assert json.loads(policy.read_text())["restore"]["transactional"] is True;assert json.loads(state.read_text())["status"]=="idle";assert "ConditionACPower=true" in service.read_text();assert "factory-reset.pending" in first_service.read_text();assert "--require-confirmation" in runner.read_text();assert "factory-reset-first-boot" in first_runner.read_text();assert [p.stat().st_mode&0o777 for p in paths]==[0o640,0o640,0o644,0o644,0o750,0o750]
def test_idempotent(tmp_path):
 plan=create_factory_reset_plan(rootfs(tmp_path),ROOT/"config/factory-reset.yaml");i=FactoryResetInstaller();paths=i.install(plan);before=[p.read_bytes() for p in paths];i.install(plan);assert before==[p.read_bytes() for p in paths]
def test_dry_run(tmp_path):
 paths=FactoryResetInstaller().install(create_factory_reset_plan(rootfs(tmp_path),ROOT/"config/factory-reset.yaml"),dry_run=True);assert len(paths)==6 and not any(p.exists() for p in paths)
def test_rejects_automatic_reset(tmp_path):
 with pytest.raises(FactoryResetError,match="seguretat"):load_factory_reset(altered(tmp_path,"automatic_reset: false","automatic_reset: true"))
def test_rejects_unattended_remote_reset(tmp_path):
 with pytest.raises(FactoryResetError,match="seguretat"):load_factory_reset(altered(tmp_path,"remote_unattended_reset: false","remote_unattended_reset: true"))
def test_rejects_unsigned_restore(tmp_path):
 with pytest.raises(FactoryResetError,match="Restauració"):load_factory_reset(altered(tmp_path,"require_signature: true","require_signature: false"))
def test_rejects_missing_identity_preservation(tmp_path):
 with pytest.raises(FactoryResetError,match="preservades"):load_factory_reset(altered(tmp_path,"device_identity: true","device_identity: false"))
def test_rejects_symlink(tmp_path):
 plan=create_factory_reset_plan(rootfs(tmp_path),ROOT/"config/factory-reset.yaml");p=plan.output("state");p.parent.mkdir(parents=True);p.symlink_to(tmp_path/"elsewhere")
 with pytest.raises(FactoryResetError,match="enllaç simbòlic"):FactoryResetInstaller().install(plan)
def test_cli(tmp_path):
 assert build_parser().parse_args(["configure-factory-reset","--dry-run"]).command=="configure-factory-reset";rootfs(tmp_path);(tmp_path/"config").mkdir();(tmp_path/"config/factory-reset.yaml").write_text((ROOT/"config/factory-reset.yaml").read_text());assert main(["--root",str(tmp_path),"configure-factory-reset","--dry-run"])==0
