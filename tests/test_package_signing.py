from pathlib import Path
import json, os
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.package_signing import PackageSigningError, PackageSigningInstaller, create_package_signing_plan, load_package_signing_policy

ROOT=Path(__file__).parents[1]

def rootfs(tmp_path:Path)->Path:
    p=tmp_path/'.build'/'rootfs'; p.mkdir(parents=True); return p

def test_load_policy():
    p=load_package_signing_policy(ROOT/'config/package-signing.yaml')
    assert p['repository']['signed_by'].endswith('.gpg')
    assert len(p['keys']['active']['fingerprint'])==40

def test_plan_manifest(tmp_path):
    plan=create_package_signing_plan(rootfs(tmp_path),ROOT/'config/package-signing.yaml')
    assert plan.manifest()['trusted_key_count']==2
    assert plan.manifest()['revoked_key_count']==1

def test_install_and_permissions(tmp_path):
    plan=create_package_signing_plan(rootfs(tmp_path),ROOT/'config/package-signing.yaml')
    paths=PackageSigningInstaller().install(plan)
    assert all(p.exists() for p in paths)
    assert 'Signed-By:' in plan.output('source').read_text()
    assert 'AllowUnauthenticated "false"' in plan.output('apt_conf').read_text()
    assert plan.output('verifier').stat().st_mode & 0o777 == 0o750
    assert json.loads(plan.output('state').read_text())['status']=='configured'

def test_idempotent(tmp_path):
    plan=create_package_signing_plan(rootfs(tmp_path),ROOT/'config/package-signing.yaml'); i=PackageSigningInstaller()
    i.install(plan); first=plan.output('policy').read_bytes(); i.install(plan)
    assert plan.output('policy').read_bytes()==first

def test_dry_run(tmp_path):
    plan=create_package_signing_plan(rootfs(tmp_path),ROOT/'config/package-signing.yaml')
    paths=PackageSigningInstaller().install(plan,dry_run=True)
    assert len(paths)==5 and not any(p.exists() for p in paths)

def test_reject_http(tmp_path):
    text=(ROOT/'config/package-signing.yaml').read_text().replace('https://','http://')
    p=tmp_path/'p.yaml'; p.write_text(text)
    with pytest.raises(PackageSigningError,match='HTTPS'): load_package_signing_policy(p)

def test_reject_revoked_trusted_key(tmp_path):
    text=(ROOT/'config/package-signing.yaml').read_text().replace('FEDCBA9876543210FEDCBA9876543210FEDCBA98','0123456789ABCDEF0123456789ABCDEF01234567')
    p=tmp_path/'p.yaml'; p.write_text(text)
    with pytest.raises(PackageSigningError,match='Conflicte'): load_package_signing_policy(p)

def test_reject_bad_fingerprint(tmp_path):
    text=(ROOT/'config/package-signing.yaml').read_text().replace('0123456789ABCDEF0123456789ABCDEF01234567','BAD')
    p=tmp_path/'p.yaml'; p.write_text(text)
    with pytest.raises(PackageSigningError,match='Fingerprint'): load_package_signing_policy(p)

def test_reject_symlink(tmp_path):
    plan=create_package_signing_plan(rootfs(tmp_path),ROOT/'config/package-signing.yaml')
    target=plan.output('policy'); target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'elsewhere')
    with pytest.raises(PackageSigningError,match='enllaç simbòlic'): PackageSigningInstaller().install(plan)

def test_cli_parser_and_dry_run(tmp_path):
    assert build_parser().parse_args(['configure-package-signing','--dry-run']).command=='configure-package-signing'
    rootfs(tmp_path); (tmp_path/'config').mkdir(); (tmp_path/'config'/'package-signing.yaml').write_text((ROOT/'config/package-signing.yaml').read_text())
    assert main(['--root',str(tmp_path),'configure-package-signing','--dry-run'])==0
