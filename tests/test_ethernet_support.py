from __future__ import annotations
import json
from pathlib import Path
import pytest
from xaac_thin_client_os.ethernet_support import (
    EthernetConfigurator, EthernetDetector, EthernetInterface, EthernetSupportError,
    compare_ethernet, create_ethernet_configuration_plan, load_ethernet_profile,
    write_ethernet_report,
)

def write(root: Path, rel: str, value: str) -> None:
    path=root/rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value, encoding="utf-8")

def iface(**changes: object) -> EthernetInterface:
    values={"name":"enp1s0","mac_address":"00:11:22:33:44:55","driver":"r8169","carrier":True,"operstate":"up","speed_mbps":1000,"duplex":"full","wake_on_lan_modes":("magic",)}
    values.update(changes); return EthernetInterface(**values)  # type: ignore[arg-type]

def test_detects_ethernet_interface(tmp_path: Path) -> None:
    base="sys/class/net/enp1s0"
    write(tmp_path,f"{base}/type","1\n"); write(tmp_path,f"{base}/address","00:11:22:33:44:55\n")
    write(tmp_path,f"{base}/carrier","1\n"); write(tmp_path,f"{base}/operstate","up\n")
    write(tmp_path,f"{base}/speed","1000\n"); write(tmp_path,f"{base}/duplex","full\n")
    write(tmp_path,f"{base}/device/power/wakeup","enabled\n")
    driver=tmp_path/f"{base}/device/driver"; driver.parent.mkdir(parents=True,exist_ok=True); driver.symlink_to(tmp_path/"drivers/r8169", target_is_directory=True)
    result=EthernetDetector(root=tmp_path).detect(); assert len(result)==1; assert result[0].speed_mbps==1000; assert result[0].driver=="r8169"

def test_loopback_and_non_ethernet_are_ignored(tmp_path: Path) -> None:
    write(tmp_path,"sys/class/net/lo/type","772\n"); write(tmp_path,"sys/class/net/wlan0/type","801\n")
    assert EthernetDetector(root=tmp_path).detect()==()

def test_missing_sysfs_is_safe(tmp_path: Path) -> None:
    assert EthernetDetector(root=tmp_path).detect()==()

def test_invalid_speed_is_unknown(tmp_path: Path) -> None:
    write(tmp_path,"sys/class/net/eth0/type","1\n"); write(tmp_path,"sys/class/net/eth0/speed","-1\n")
    assert EthernetDetector(root=tmp_path).detect()[0].speed_mbps is None

def test_profile_loads(project_root: Path) -> None:
    assert load_ethernet_profile(project_root/"config/ethernet.yaml")["profile"]=="wyse3040"

@pytest.mark.parametrize("content",["[]\n","schema_version: 2\n","schema_version: 1\nprofile: x\n"])
def test_invalid_profile_rejected(tmp_path: Path, content: str) -> None:
    path=tmp_path/"ethernet.yaml"; path.write_text(content,encoding="utf-8")
    with pytest.raises(EthernetSupportError): load_ethernet_profile(path)

def test_compatible_ethernet_passes(project_root: Path) -> None:
    report=compare_ethernet((iface(),),load_ethernet_profile(project_root/"config/ethernet.yaml")); assert report.compatible; assert report.selected_interface is not None

def test_best_interface_is_selected(project_root: Path) -> None:
    report=compare_ethernet((iface(name="enp2s0",carrier=False,speed_mbps=100),iface()),load_ethernet_profile(project_root/"config/ethernet.yaml")); assert report.selected_interface and report.selected_interface.name=="enp1s0"

def test_absent_interface_fails(project_root: Path) -> None:
    report=compare_ethernet((),load_ethernet_profile(project_root/"config/ethernet.yaml")); assert not report.compatible

def test_slow_link_fails(project_root: Path) -> None:
    report=compare_ethernet((iface(speed_mbps=10),),load_ethernet_profile(project_root/"config/ethernet.yaml")); assert not report.compatible

def test_unknown_speed_warns_but_passes(project_root: Path) -> None:
    report=compare_ethernet((iface(speed_mbps=None),),load_ethernet_profile(project_root/"config/ethernet.yaml")); assert report.compatible; assert next(c for c in report.checks if c.name=="link-speed").status=="warning"

def test_disconnected_link_warns_but_passes(project_root: Path) -> None:
    report=compare_ethernet((iface(carrier=False,operstate="down"),),load_ethernet_profile(project_root/"config/ethernet.yaml")); assert report.compatible

def test_invalid_mac_fails(project_root: Path) -> None:
    assert not compare_ethernet((iface(mac_address="bad"),),load_ethernet_profile(project_root/"config/ethernet.yaml")).compatible

def test_alternative_driver_is_warning(project_root: Path) -> None:
    report=compare_ethernet((iface(driver="igc"),),load_ethernet_profile(project_root/"config/ethernet.yaml")); assert report.compatible; assert next(c for c in report.checks if c.name=="driver").status=="warning"

def test_dhcp_plan_and_execution(tmp_path: Path, project_root: Path) -> None:
    plan=create_ethernet_configuration_plan(tmp_path/"build/rootfs",project_root/"config/ethernet.yaml")
    assert plan.mode=="dhcp"; assert EthernetConfigurator().execute(plan,dry_run=True)==()
    written=EthernetConfigurator().execute(plan); assert len(written)==2; assert "DHCP=ipv4" in written[0].read_text(); assert (plan.rootfs/"etc/systemd/system/multi-user.target.wants/systemd-networkd.service").is_symlink()

def test_static_plan(project_root: Path, tmp_path: Path) -> None:
    plan=create_ethernet_configuration_plan(tmp_path/"build/rootfs",project_root/"config/ethernet.yaml",mode="static",address="192.0.2.10/24",gateway="192.0.2.1",dns=("192.0.2.53",))
    content=plan.files[0][1]; assert "Address=192.0.2.10/24" in content; assert "Gateway=192.0.2.1" in content; assert "DNS=192.0.2.53" in content

@pytest.mark.parametrize("kwargs",[{"mode":"static"},{"mode":"static","address":"bad"},{"mode":"static","address":"2001:db8::1/64"},{"mode":"static","address":"192.0.2.10/24","gateway":"bad"},{"mode":"static","address":"192.0.2.10/24","dns":("bad",)}])
def test_invalid_static_configuration_rejected(project_root: Path, tmp_path: Path, kwargs: dict[str, object]) -> None:
    with pytest.raises(EthernetSupportError): create_ethernet_configuration_plan(tmp_path/"build/rootfs",project_root/"config/ethernet.yaml",**kwargs)  # type: ignore[arg-type]

def test_unsafe_rootfs_rejected(project_root: Path) -> None:
    with pytest.raises(EthernetSupportError,match="Rootfs insegur"): create_ethernet_configuration_plan(Path("/"),project_root/"config/ethernet.yaml")

def test_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    plan=create_ethernet_configuration_plan(tmp_path/"build/rootfs",project_root/"config/ethernet.yaml"); target=plan.rootfs/"etc/systemd/network/20-xaac-ethernet.network"; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/"other")
    with pytest.raises(EthernetSupportError,match="enllaç simbòlic"): EthernetConfigurator().execute(plan)

def test_report_written_atomically(tmp_path: Path, project_root: Path) -> None:
    report=compare_ethernet((iface(),),load_ethernet_profile(project_root/"config/ethernet.yaml")); destination=tmp_path/"reports/ethernet.json"; write_ethernet_report(report,destination); assert json.loads(destination.read_text())["compatible"] is True; assert not destination.with_suffix(".json.tmp").exists()

def test_cli_parser_accepts_ethernet_commands(project_root: Path) -> None:
    from xaac_thin_client_os.cli import build_parser
    args=build_parser().parse_args(["--root",str(project_root),"configure-ethernet","--dry-run","--mode","static","--address","192.0.2.10/24","--dns","192.0.2.53"])
    assert args.command=="configure-ethernet"; assert args.mode=="static"; assert args.dns==["192.0.2.53"]

def test_cli_inspect_ethernet_json(monkeypatch: pytest.MonkeyPatch, project_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from xaac_thin_client_os.cli import main
    monkeypatch.setattr("xaac_thin_client_os.cli.EthernetDetector.detect",lambda self:(iface(),))
    assert main(["--root",str(project_root),"--json","inspect-ethernet"])==0
    assert json.loads(capsys.readouterr().out)["selected_interface"]["name"]=="enp1s0"

def test_report_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    report=compare_ethernet((iface(),),load_ethernet_profile(project_root/"config/ethernet.yaml")); destination=tmp_path/"ethernet.json"; destination.symlink_to(tmp_path/"other")
    with pytest.raises(EthernetSupportError,match="enllaç simbòlic"): write_ethernet_report(report,destination)
