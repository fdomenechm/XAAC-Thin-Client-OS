from pathlib import Path
import json, pytest
from xaac_thin_client_os.recovery_partition import RecoveryPartitionError, RecoveryPartitionInstaller, create_recovery_partition_plan, load_recovery_partition
from xaac_thin_client_os.cli import build_parser, main
ROOT=Path(__file__).parents[1]
def rootfs(tmp_path):
 p=tmp_path/".build/rootfs";p.mkdir(parents=True);return p
def altered(tmp_path,old,new):
 p=tmp_path/"recovery-partition.yaml";p.write_text((ROOT/"config/recovery-partition.yaml").read_text().replace(old,new));return p
def test_loads_recovery_partition():
 p=load_recovery_partition(ROOT/"config/recovery-partition.yaml");assert p["partition"]["read_only"] is True and p["image"]["require_signature"] is True
def test_manifest_is_stable(tmp_path):
 assert create_recovery_partition_plan(rootfs(tmp_path),ROOT/"config/recovery-partition.yaml").manifest()=={"schema_version":1,"partition_id":"xaac-recovery-partition-1","label":"XAAC_RECOVERY","minimum_size_mib":768,"tool_count":6,"read_only":True}
def test_installs_partition_assets(tmp_path):
 paths=RecoveryPartitionInstaller().install(create_recovery_partition_plan(rootfs(tmp_path),ROOT/"config/recovery-partition.yaml"));policy,state,mount,service,verifier,grub=paths
 assert json.loads(policy.read_text())["partition"]["label"]=="XAAC_RECOVERY";assert json.loads(state.read_text())["status"]=="unverified";assert "Options=ro,nodev,nosuid,noexec" in mount.read_text();assert "ProtectSystem=strict" in service.read_text();assert "verify-partition" in verifier.read_text();assert "search --no-floppy --label XAAC_RECOVERY" in grub.read_text()
 assert [p.stat().st_mode&0o777 for p in paths]==[0o640,0o640,0o644,0o644,0o750,0o750]
def test_idempotent(tmp_path):
 plan=create_recovery_partition_plan(rootfs(tmp_path),ROOT/"config/recovery-partition.yaml");i=RecoveryPartitionInstaller();paths=i.install(plan);before=[p.read_bytes() for p in paths];i.install(plan);assert before==[p.read_bytes() for p in paths]
def test_dry_run(tmp_path):
 paths=RecoveryPartitionInstaller().install(create_recovery_partition_plan(rootfs(tmp_path),ROOT/"config/recovery-partition.yaml"),dry_run=True);assert len(paths)==6 and not any(p.exists() for p in paths)
def test_rejects_writable_partition(tmp_path):
 with pytest.raises(RecoveryPartitionError,match="Partició"):load_recovery_partition(altered(tmp_path,"read_only: true","read_only: false"))
def test_rejects_unsigned_image(tmp_path):
 with pytest.raises(RecoveryPartitionError,match="Imatge"):load_recovery_partition(altered(tmp_path,"require_signature: true","require_signature: false"))
def test_rejects_factory_reset(tmp_path):
 with pytest.raises(RecoveryPartitionError,match="prohibit"):load_recovery_partition(altered(tmp_path,"automatic_factory_reset: false","automatic_factory_reset: true"))
def test_rejects_symlink(tmp_path):
 plan=create_recovery_partition_plan(rootfs(tmp_path),ROOT/"config/recovery-partition.yaml");p=plan.output("state");p.parent.mkdir(parents=True);p.symlink_to(tmp_path/"elsewhere")
 with pytest.raises(RecoveryPartitionError,match="enllaç simbòlic"):RecoveryPartitionInstaller().install(plan)
def test_cli(tmp_path):
 assert build_parser().parse_args(["configure-recovery-partition","--dry-run"]).command=="configure-recovery-partition";rootfs(tmp_path);(tmp_path/"config").mkdir();(tmp_path/"config/recovery-partition.yaml").write_text((ROOT/"config/recovery-partition.yaml").read_text());assert main(["--root",str(tmp_path),"configure-recovery-partition","--dry-run"])==0
