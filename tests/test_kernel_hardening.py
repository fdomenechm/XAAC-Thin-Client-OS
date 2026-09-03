from __future__ import annotations
import json
from pathlib import Path
import pytest, yaml
from xaac_thin_client_os.kernel_hardening import KernelHardeningError, KernelHardeningInstaller, create_kernel_hardening_plan, load_kernel_hardening_policy
from xaac_thin_client_os.cli import build_parser, main
PROFILE=Path('config/kernel-hardening.yaml')

def test_policy_loads_required_controls():
    p=load_kernel_hardening_policy(PROFILE)
    assert p['sysctl']['kernel.randomize_va_space']==2
    assert p['sysctl']['kernel.yama.ptrace_scope']==2
    assert 'sctp' in p['module_policy']['disabled']
    assert 'squashfs' not in p['module_policy']['disabled']
    assert 'squashfs' in p['module_policy']['allowed_runtime']

def test_unsafe_rootfs_rejected(tmp_path):
    with pytest.raises(KernelHardeningError,match='Rootfs insegur'): create_kernel_hardening_plan(tmp_path,PROFILE)

def test_missing_required_control_rejected(tmp_path):
    d=yaml.safe_load(PROFILE.read_text()); d['sysctl']['kernel.sysrq']=1; f=tmp_path/'p.yaml'; f.write_text(yaml.safe_dump(d))
    with pytest.raises(KernelHardeningError,match='obligatoris'): load_kernel_hardening_policy(f)

def test_module_conflict_rejected(tmp_path):
    d=yaml.safe_load(PROFILE.read_text()); d['module_policy']['allowed_runtime'].append('sctp'); f=tmp_path/'p.yaml'; f.write_text(yaml.safe_dump(d))
    with pytest.raises(KernelHardeningError,match='permés i deshabilitat'): load_kernel_hardening_policy(f)

def test_unsafe_output_rejected(tmp_path):
    d=yaml.safe_load(PROFILE.read_text()); d['outputs']['state']='/var/../etc/x'; f=tmp_path/'p.yaml'; f.write_text(yaml.safe_dump(d))
    with pytest.raises(KernelHardeningError,match='Ruta insegura'): load_kernel_hardening_policy(f)

def test_install_writes_controls_and_state(tmp_path):
    plan=create_kernel_hardening_plan(tmp_path/'rootfs',PROFILE); paths=KernelHardeningInstaller().install(plan)
    assert len(paths)==5
    text=plan.destination('sysctl').read_text(); assert 'kernel.randomize_va_space = 2' in text and 'kernel.sysrq = 0' in text
    mods=plan.destination('modules').read_text(); assert 'install sctp /bin/false' in mods and 'blacklist udf' in mods
    assert 'squashfs' not in mods
    assert plan.destination('sysctl').stat().st_mode & 0o777==0o644
    state=json.loads(plan.destination('state').read_text()); assert state['core_dumps_disabled'] is True

def test_install_idempotent(tmp_path):
    plan=create_kernel_hardening_plan(tmp_path/'rootfs',PROFILE); i=KernelHardeningInstaller(); i.install(plan); before={p:p.read_bytes() for p in i.install(plan,dry_run=True)}; i.install(plan); assert before=={p:p.read_bytes() for p in before}

def test_symlink_rejected(tmp_path):
    plan=create_kernel_hardening_plan(tmp_path/'rootfs',PROFILE); t=plan.destination('sysctl'); t.parent.mkdir(parents=True); t.symlink_to(tmp_path/'x')
    with pytest.raises(KernelHardeningError,match='enllaç simbòlic'): KernelHardeningInstaller().install(plan)

def test_dry_run_does_not_write(tmp_path):
    plan=create_kernel_hardening_plan(tmp_path/'rootfs',PROFILE); paths=KernelHardeningInstaller().install(plan,dry_run=True); assert all(not p.exists() for p in paths)

def test_cli_exposes_kernel_hardening(tmp_path):
    assert build_parser().parse_args(['configure-kernel-hardening','--dry-run']).command=='configure-kernel-hardening'
    root=tmp_path/'project'; (root/'config').mkdir(parents=True); (root/'config/kernel-hardening.yaml').write_bytes(PROFILE.read_bytes())
    assert main(['--root',str(root),'configure-kernel-hardening','--dry-run'])==0
