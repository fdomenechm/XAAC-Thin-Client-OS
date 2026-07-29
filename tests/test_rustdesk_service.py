from pathlib import Path
import json
import pytest
from xaac_thin_client_os.rustdesk_service import RustDeskServiceError, RustDeskServiceInstaller, create_rustdesk_service_plan, load_rustdesk_service_profile

def test_profile_defines_service_user_restart_and_sandbox(project_root: Path) -> None:
    p=load_rustdesk_service_profile(project_root/'config/rustdesk-service.yaml')
    assert p['service']['user']=='xaac-rustdesk'; assert p['service']['restart']=='on-failure'; assert p['sandbox']['no_new_privileges'] is True

def test_installer_writes_unit_user_directories_and_state(project_root: Path,tmp_path: Path) -> None:
    plan=create_rustdesk_service_plan(tmp_path/'rootfs',project_root/'config/rustdesk-service.yaml')
    files=RustDeskServiceInstaller().install(plan)
    assert len(files)==4
    unit=plan.target('unit').read_text(); assert 'User=xaac-rustdesk' in unit and 'Restart=on-failure' in unit and 'ProtectSystem=strict' in unit
    assert 'u xaac-rustdesk' in plan.target('sysusers').read_text()
    assert '/run/xaac/rustdesk' in plan.target('tmpfiles').read_text()
    state=json.loads(plan.target('state').read_text()); assert state['enabled'] is False and state['activation']=='on-demand'

def test_state_has_restricted_permissions(project_root: Path,tmp_path: Path) -> None:
    plan=create_rustdesk_service_plan(tmp_path/'rootfs',project_root/'config/rustdesk-service.yaml'); RustDeskServiceInstaller().install(plan)
    assert plan.target('state').stat().st_mode & 0o777 == 0o640

def test_dry_run_does_not_create_rootfs(project_root: Path,tmp_path: Path) -> None:
    plan=create_rustdesk_service_plan(tmp_path/'rootfs',project_root/'config/rustdesk-service.yaml')
    assert RustDeskServiceInstaller().install(plan,dry_run=True)==() and not plan.rootfs.exists()

def test_rejects_unsafe_output(project_root: Path,tmp_path: Path) -> None:
    text=(project_root/'config/rustdesk-service.yaml').read_text().replace('/etc/systemd/system/rustdesk-xaac.service','../escape')
    bad=tmp_path/'bad.yaml'; bad.write_text(text)
    with pytest.raises(RustDeskServiceError,match='Ruta insegura'): load_rustdesk_service_profile(bad)

def test_rejects_symlink_target(project_root: Path,tmp_path: Path) -> None:
    plan=create_rustdesk_service_plan(tmp_path/'rootfs',project_root/'config/rustdesk-service.yaml'); target=plan.target('unit'); target.parent.mkdir(parents=True); target.symlink_to(tmp_path/'outside')
    with pytest.raises(RustDeskServiceError,match='enllaç simbòlic'): RustDeskServiceInstaller().install(plan)

def test_cli_exposes_rustdesk_service_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    assert build_parser().parse_args(['configure-rustdesk-service','--dry-run']).command=='configure-rustdesk-service'
