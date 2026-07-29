from pathlib import Path
import pytest
from xaac_thin_client_os.display_layout import DisplayLayoutConfigurator, DisplayLayoutError, DisplayOutput, compare_display_layout, create_display_layout_plan, load_display_layout_profile

def outputs(**change: object) -> tuple[DisplayOutput,...]:
    vals=dict(name="DP-1",connected=True,primary=True,width=1920,height=1080,scale=1.0,x=0,y=0); vals.update(change)
    return (DisplayOutput(**vals),)  # type: ignore[arg-type]

def test_profile_wayland_x11_hotplug_and_freerdp(project_root: Path) -> None:
    p=load_display_layout_profile(project_root/"config/display-layout.yaml")
    assert p["backend"]=={"primary":"wayland","fallback":"x11"}; assert p["layout"]["hotplug"]
    assert p["freerdp"]["multimon"] and p["freerdp"]["dynamic_resolution"]

def test_single_and_dual_monitor_are_valid(project_root: Path) -> None:
    p=load_display_layout_profile(project_root/"config/display-layout.yaml")
    assert compare_display_layout(outputs(),p).compatible
    dual=outputs()+(DisplayOutput("DP-2",True,False,1280,1024,1.25,1920,0),)
    assert compare_display_layout(dual,p).compatible

@pytest.mark.parametrize("value,check", [
    ((DisplayOutput("DP-1",False,False,0,0,1,0,0),),"outputs"),
    (outputs(primary=False),"primary"),(outputs(width=800),"resolution"),(outputs(scale=2.5),"scaling"),
])
def test_invalid_runtime(value: tuple[DisplayOutput,...], check: str, project_root: Path) -> None:
    r=compare_display_layout(value,load_display_layout_profile(project_root/"config/display-layout.yaml")); assert not r.compatible
    assert next(x for x in r.checks if x["name"]==check)["status"]=="fail"

def test_overlapping_dual_monitor_fails(project_root: Path) -> None:
    value=outputs()+(DisplayOutput("DP-2",True,False,1280,1024,1,0,0),)
    assert not compare_display_layout(value,load_display_layout_profile(project_root/"config/display-layout.yaml")).compatible

def test_plan_contains_scripts_service_and_freerdp(tmp_path: Path, project_root: Path) -> None:
    plan=create_display_layout_plan(tmp_path/"build/rootfs",project_root/"config/display-layout.yaml"); data={str(p):c for p,c,_ in plan.files}
    assert {"wlr-randr","x11-xserver-utils"}<=set(plan.packages)
    assert "--preferred" in data["/usr/local/libexec/xaac-display-layout-wayland"]
    assert "xrandr --auto" in data["/usr/local/libexec/xaac-display-layout-x11"]
    assert "/multimon" in data["/etc/xaac/session/freerdp-display.env"]

def test_execute_idempotent_and_dry_run(tmp_path: Path, project_root: Path) -> None:
    plan=create_display_layout_plan(tmp_path/"build/rootfs",project_root/"config/display-layout.yaml"); cfg=DisplayLayoutConfigurator(); assert cfg.execute(plan,dry_run=True)==()
    first=cfg.execute(plan); before=[p.read_bytes() for p in first]; second=cfg.execute(plan); assert [p.read_bytes() for p in second]==before

def test_unsafe_root_and_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    with pytest.raises(DisplayLayoutError,match="Rootfs insegur"): create_display_layout_plan(Path("/"),project_root/"config/display-layout.yaml")
    plan=create_display_layout_plan(tmp_path/"build/rootfs",project_root/"config/display-layout.yaml"); target=plan.rootfs/"etc/xaac/session/display-layout-policy.json"; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/"x")
    with pytest.raises(DisplayLayoutError,match="enllaç simbòlic"): DisplayLayoutConfigurator().execute(plan)

@pytest.mark.parametrize("old,new",[("primary: wayland","primary: weston"),("hotplug: true","hotplug: false"),("maximum: 2.0","maximum: 0.5"),("multimon: true","multimon: false"),("policy: /etc/xaac/session/display-layout-policy.json","policy: ../bad")])
def test_invalid_profiles(tmp_path: Path,project_root: Path,old: str,new: str) -> None:
    text=(project_root/"config/display-layout.yaml").read_text().replace(old,new); path=tmp_path/"p.yaml"; path.write_text(text)
    with pytest.raises(DisplayLayoutError): load_display_layout_profile(path)

def test_cli_exposes_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    a=build_parser().parse_args(["configure-display-layout","--dry-run"]); assert a.command=="configure-display-layout" and a.dry_run
