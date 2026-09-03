from pathlib import Path
import pytest
from xaac_thin_client_os.graphical_session_validation import GraphicalSessionObservation, GraphicalSessionValidationConfigurator, GraphicalSessionValidationError, create_graphical_session_validation_plan, load_graphical_session_validation_profile, validate_graphical_session

def observation(**change: object) -> GraphicalSessionObservation:
    values=dict(greetd_active=True,wayland_display=True,compositor="labwc",client_running=True,startup_seconds=12.0,idle_memory_mb=220,idle_cpu_percent=2.0,failed_units=0,processes=("labwc","xaac-thin-client"),kiosk_shell="/usr/sbin/nologin"); values.update(change)
    return GraphicalSessionObservation(**values)  # type: ignore[arg-type]

def test_profile_covers_complete_session(project_root:Path)->None:
    p=load_graphical_session_validation_profile(project_root/"config/graphical-session-validation.yaml")
    assert p["startup"]["require_compositor"]=="labwc"; assert "gnome-terminal" in p["restrictions"]["forbidden_terminals"]

def test_healthy_session_passes(project_root:Path)->None:
    assert validate_graphical_session(observation(),load_graphical_session_validation_profile(project_root/"config/graphical-session-validation.yaml")).compatible

@pytest.mark.parametrize("changes,check",[(("greetd_active",False),"greetd"),(("wayland_display",False),"wayland"),(("compositor","weston"),"compositor"),(("client_running",False),"client"),(("startup_seconds",31.0),"startup_time"),(("idle_memory_mb",513),"idle_memory"),(("idle_cpu_percent",16.0),"idle_cpu"),(("failed_units",1),"failed_units"),(("processes",("labwc","xterm")),"forbidden_processes"),(("kiosk_shell","/bin/bash"),"kiosk_shell")])
def test_unhealthy_session_fails(changes:tuple[str,object],check:str,project_root:Path)->None:
    r=validate_graphical_session(observation(**{changes[0]:changes[1]}),load_graphical_session_validation_profile(project_root/"config/graphical-session-validation.yaml")); assert not r.compatible; assert next(x for x in r.checks if x["name"]==check)["status"]=="fail"

def test_plan_contains_validator_service_and_policy(tmp_path:Path,project_root:Path)->None:
    plan=create_graphical_session_validation_plan(tmp_path/"build/rootfs",project_root/"config/graphical-session-validation.yaml"); data={str(p):c for p,c,_ in plan.files}
    assert "systemctl --failed" in data["/usr/local/libexec/xaac-validate-graphical-session"]; assert "WantedBy=graphical.target" in data["/usr/lib/systemd/system/xaac-graphical-session-validation.service"]

def test_execute_is_idempotent_and_dry_run(tmp_path:Path,project_root:Path)->None:
    plan=create_graphical_session_validation_plan(tmp_path/"build/rootfs",project_root/"config/graphical-session-validation.yaml"); cfg=GraphicalSessionValidationConfigurator(); assert cfg.execute(plan,dry_run=True)==(); first=cfg.execute(plan); before=[p.read_bytes() for p in first]; second=cfg.execute(plan); assert [p.read_bytes() for p in second]==before

def test_unsafe_root_and_symlink_rejected(tmp_path:Path,project_root:Path)->None:
    with pytest.raises(GraphicalSessionValidationError,match="Rootfs insegur"): create_graphical_session_validation_plan(Path("/"),project_root/"config/graphical-session-validation.yaml")
    plan=create_graphical_session_validation_plan(tmp_path/"build/rootfs",project_root/"config/graphical-session-validation.yaml"); target=plan.rootfs/"etc/xaac/session/graphical-session-validation-policy.json"; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/"x")
    with pytest.raises(GraphicalSessionValidationError,match="enllaç simbòlic"): GraphicalSessionValidationConfigurator().execute(plan)

@pytest.mark.parametrize("old,new",[("require_compositor: labwc","require_compositor: weston"),("maximum_startup_seconds: 30","maximum_startup_seconds: 0"),("maximum_idle_memory_mb: 512","maximum_idle_memory_mb: 32"),("observation_seconds: 300","observation_seconds: 10"),("forbid_interactive_shell: true","forbid_interactive_shell: false"),("policy: /etc/xaac/session/graphical-session-validation-policy.json","policy: ../bad")])
def test_invalid_profiles(tmp_path:Path,project_root:Path,old:str,new:str)->None:
    path=tmp_path/"p.yaml"; path.write_text((project_root/"config/graphical-session-validation.yaml").read_text().replace(old,new))
    with pytest.raises(GraphicalSessionValidationError): load_graphical_session_validation_profile(path)

def test_cli_exposes_command()->None:
    from xaac_thin_client_os.cli import build_parser
    a=build_parser().parse_args(["validate-graphical-session","--dry-run"]); assert a.command=="validate-graphical-session" and a.dry_run
