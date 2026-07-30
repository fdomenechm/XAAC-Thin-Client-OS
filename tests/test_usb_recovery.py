from pathlib import Path
import json, pytest
from xaac_thin_client_os.usb_recovery import UsbRecoveryError, UsbRecoveryInstaller, create_usb_recovery_plan, load_usb_recovery
from xaac_thin_client_os.cli import build_parser, main
ROOT=Path(__file__).parents[1]
def rootfs(tmp_path):
 p=tmp_path/".build/rootfs";p.mkdir(parents=True);return p
def altered(tmp_path,old,new):
 p=tmp_path/"usb-recovery.yaml";p.write_text((ROOT/"config/usb-recovery.yaml").read_text().replace(old,new));return p
def test_loads_usb_recovery():
 p=load_usb_recovery(ROOT/"config/usb-recovery.yaml");assert p["detection"]["removable_only"] is True and p["trust"]["require_signature"] is True
def test_manifest_is_stable(tmp_path):
 assert create_usb_recovery_plan(rootfs(tmp_path),ROOT/"config/usb-recovery.yaml").manifest()=={"schema_version":1,"recovery_id":"xaac-usb-recovery-1","label":"XAAC_RECOVERY_USB","hash_algorithm":"sha256","signature_required":True,"downgrade_allowed":False}
def test_installs_usb_recovery_assets(tmp_path):
 paths=UsbRecoveryInstaller().install(create_usb_recovery_plan(rootfs(tmp_path),ROOT/"config/usb-recovery.yaml"));policy,state,udev,service,runner=paths
 assert json.loads(policy.read_text())["version"]["allow_downgrade"] is False;assert json.loads(state.read_text())["status"]=="idle";assert "XAAC_RECOVERY_USB" in udev.read_text();assert "ConditionACPower=true" in service.read_text();assert "--verify-signature" in runner.read_text();assert [p.stat().st_mode&0o777 for p in paths]==[0o640,0o640,0o644,0o644,0o750]
def test_idempotent(tmp_path):
 plan=create_usb_recovery_plan(rootfs(tmp_path),ROOT/"config/usb-recovery.yaml");i=UsbRecoveryInstaller();paths=i.install(plan);before=[p.read_bytes() for p in paths];i.install(plan);assert before==[p.read_bytes() for p in paths]
def test_dry_run(tmp_path):
 paths=UsbRecoveryInstaller().install(create_usb_recovery_plan(rootfs(tmp_path),ROOT/"config/usb-recovery.yaml"),dry_run=True);assert len(paths)==5 and not any(p.exists() for p in paths)
def test_rejects_unsigned_media(tmp_path):
 with pytest.raises(UsbRecoveryError,match="Confiança"):load_usb_recovery(altered(tmp_path,"require_signature: true","require_signature: false"))
def test_rejects_non_removable_media(tmp_path):
 with pytest.raises(UsbRecoveryError,match="Detecció"):load_usb_recovery(altered(tmp_path,"removable_only: true","removable_only: false"))
def test_rejects_downgrade(tmp_path):
 with pytest.raises(UsbRecoveryError,match="versió"):load_usb_recovery(altered(tmp_path,"allow_downgrade: false","allow_downgrade: true"))
def test_rejects_wrong_hardware_policy(tmp_path):
 with pytest.raises(UsbRecoveryError,match="mitjà incorrecte"):load_usb_recovery(altered(tmp_path,"reject_wrong_hardware: true","reject_wrong_hardware: false"))
def test_rejects_symlink(tmp_path):
 plan=create_usb_recovery_plan(rootfs(tmp_path),ROOT/"config/usb-recovery.yaml");p=plan.output("state");p.parent.mkdir(parents=True);p.symlink_to(tmp_path/"elsewhere")
 with pytest.raises(UsbRecoveryError,match="enllaç simbòlic"):UsbRecoveryInstaller().install(plan)
def test_cli(tmp_path):
 assert build_parser().parse_args(["configure-usb-recovery","--dry-run"]).command=="configure-usb-recovery";rootfs(tmp_path);(tmp_path/"config").mkdir();(tmp_path/"config/usb-recovery.yaml").write_text((ROOT/"config/usb-recovery.yaml").read_text());assert main(["--root",str(tmp_path),"configure-usb-recovery","--dry-run"])==0
