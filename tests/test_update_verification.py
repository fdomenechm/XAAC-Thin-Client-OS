from pathlib import Path
import json, pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.update_verification import UpdateVerificationError, UpdateVerificationInstaller, create_update_verification_plan, load_update_verification
ROOT=Path(__file__).parents[1]
def rootfs(tmp_path):
    p=tmp_path/'.build/rootfs';p.mkdir(parents=True);return p
def altered(tmp_path,old,new):
    p=tmp_path/'verification.yaml';p.write_text((ROOT/'config/update-verification.yaml').read_text().replace(old,new));return p
def test_loads_verification_policy():
    p=load_update_verification(ROOT/'config/update-verification.yaml');assert p['hashes']['algorithms']==['sha256','sha512']
def test_manifest_is_stable(tmp_path):
    assert create_update_verification_plan(rootfs(tmp_path),ROOT/'config/update-verification.yaml').manifest()['hardware_profile']=='wyse3040'
def test_installs_policy_state_and_verifier(tmp_path):
    p,s,v=UpdateVerificationInstaller().install(create_update_verification_plan(rootfs(tmp_path),ROOT/'config/update-verification.yaml'));assert json.loads(s.read_text())['status']=='idle';assert 'verify-staged' in v.read_text();assert p.stat().st_mode&0o777==0o640;assert v.stat().st_mode&0o777==0o750
def test_installation_is_idempotent(tmp_path):
    plan=create_update_verification_plan(rootfs(tmp_path),ROOT/'config/update-verification.yaml');i=UpdateVerificationInstaller();paths=i.install(plan);before=[p.read_bytes() for p in paths];i.install(plan);assert before==[p.read_bytes() for p in paths]
def test_dry_run_does_not_write(tmp_path):
    paths=UpdateVerificationInstaller().install(create_update_verification_plan(rootfs(tmp_path),ROOT/'config/update-verification.yaml'),dry_run=True);assert len(paths)==3 and not any(p.exists() for p in paths)
def test_rejects_optional_signature(tmp_path):
    with pytest.raises(UpdateVerificationError,match='signatura'):load_update_verification(altered(tmp_path,'require_signature: true','require_signature: false'))
def test_rejects_weak_hash(tmp_path):
    with pytest.raises(UpdateVerificationError,match='hash'):load_update_verification(altered(tmp_path,'[sha256, sha512]','[sha1, sha256]'))
def test_rejects_wrong_architecture(tmp_path):
    with pytest.raises(UpdateVerificationError,match='Compatibilitat'):load_update_verification(altered(tmp_path,'architecture: amd64','architecture: arm64'))
def test_rejects_downgrade(tmp_path):
    with pytest.raises(UpdateVerificationError,match='Compatibilitat'):load_update_verification(altered(tmp_path,'allow_downgrade: false','allow_downgrade: true'))
def test_rejects_insecure_path(tmp_path):
    with pytest.raises(UpdateVerificationError,match='Ruta insegura'):load_update_verification(altered(tmp_path,'/var/lib/xaac-update/staging','../staging'))
def test_rejects_symlink_destination(tmp_path):
    plan=create_update_verification_plan(rootfs(tmp_path),ROOT/'config/update-verification.yaml');target=plan.output('state');target.parent.mkdir(parents=True);target.symlink_to(tmp_path/'elsewhere')
    with pytest.raises(UpdateVerificationError,match='enllaç simbòlic'):UpdateVerificationInstaller().install(plan)
def test_cli_supports_update_verification(tmp_path):
    assert build_parser().parse_args(['configure-update-verification','--dry-run']).command=='configure-update-verification';rootfs(tmp_path);(tmp_path/'config').mkdir();(tmp_path/'config/update-verification.yaml').write_text((ROOT/'config/update-verification.yaml').read_text());assert main(['--root',str(tmp_path),'configure-update-verification','--dry-run'])==0
