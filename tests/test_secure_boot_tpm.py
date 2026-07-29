from pathlib import Path
import json
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.secure_boot_tpm import SecureBootTpmError, SecureBootTpmInstaller, create_secure_boot_tpm_plan, load_secure_boot_tpm_policy
ROOT=Path(__file__).parents[1]
def rootfs(tmp_path):
    p=tmp_path/'.build'/'rootfs'; p.mkdir(parents=True); return p
def test_load_policy():
    p=load_secure_boot_tpm_policy(ROOT/'config/secure-boot-tpm.yaml'); assert p['secure_boot']['feasibility']=='conditional' and p['tpm']['feasibility']=='optional'
def test_plan_manifest(tmp_path):
    m=create_secure_boot_tpm_plan(rootfs(tmp_path),ROOT/'config/secure-boot-tpm.yaml').manifest(); assert m['accepted_risk_count']==2
def test_install_outputs_and_modes(tmp_path):
    plan=create_secure_boot_tpm_plan(rootfs(tmp_path),ROOT/'config/secure-boot-tpm.yaml'); paths=SecureBootTpmInstaller().install(plan)
    assert all(p.exists() for p in paths); assert plan.output('probe').stat().st_mode & 0o777 == 0o750; assert json.loads(plan.output('state').read_text())['status']=='configured'
def test_adr_records_decision(tmp_path):
    plan=create_secure_boot_tpm_plan(rootfs(tmp_path),ROOT/'config/secure-boot-tpm.yaml'); SecureBootTpmInstaller().install(plan); assert 'TPM 2.0 serà opcional' in plan.output('adr').read_text()
def test_idempotent(tmp_path):
    plan=create_secure_boot_tpm_plan(rootfs(tmp_path),ROOT/'config/secure-boot-tpm.yaml'); i=SecureBootTpmInstaller(); i.install(plan); a=plan.output('policy').read_bytes(); i.install(plan); assert a==plan.output('policy').read_bytes()
def test_dry_run(tmp_path):
    plan=create_secure_boot_tpm_plan(rootfs(tmp_path),ROOT/'config/secure-boot-tpm.yaml'); paths=SecureBootTpmInstaller().install(plan,dry_run=True); assert len(paths)==4 and not any(p.exists() for p in paths)
def test_reject_tpm_required_for_boot(tmp_path):
    text=(ROOT/'config/secure-boot-tpm.yaml').read_text().replace('required_for_boot: false','required_for_boot: true'); p=tmp_path/'p.yaml'; p.write_text(text)
    with pytest.raises(SecureBootTpmError,match='obligatori'): load_secure_boot_tpm_policy(p)
def test_reject_unsigned_kernel(tmp_path):
    text=(ROOT/'config/secure-boot-tpm.yaml').read_text().replace('require_signed_kernel: true','require_signed_kernel: false'); p=tmp_path/'p.yaml'; p.write_text(text)
    with pytest.raises(SecureBootTpmError,match='sense signar'): load_secure_boot_tpm_policy(p)
def test_reject_symlink(tmp_path):
    plan=create_secure_boot_tpm_plan(rootfs(tmp_path),ROOT/'config/secure-boot-tpm.yaml'); target=plan.output('policy'); target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'elsewhere')
    with pytest.raises(SecureBootTpmError,match='enllaç simbòlic'): SecureBootTpmInstaller().install(plan)
def test_cli_parser_and_dry_run(tmp_path):
    assert build_parser().parse_args(['configure-secure-boot-tpm','--dry-run']).command=='configure-secure-boot-tpm'
    rootfs(tmp_path); (tmp_path/'config').mkdir(); (tmp_path/'config'/'secure-boot-tpm.yaml').write_text((ROOT/'config/secure-boot-tpm.yaml').read_text())
    assert main(['--root',str(tmp_path),'configure-secure-boot-tpm','--dry-run'])==0
