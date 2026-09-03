from __future__ import annotations
import json
from pathlib import Path
import pytest
from xaac_thin_client_os.power_thermal import *

def write(root:Path,rel:str,value:str):
 p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value,encoding='utf-8')

def inv(**kw):
 d=dict(governors=('schedutil',),available_governors=('powersave','schedutil'),temperatures_celsius=(55.0,),watchdog_devices=('watchdog0',),uefi=True);d.update(kw);return PowerInventory(**d)

def test_detector(tmp_path):
 write(tmp_path,'sys/devices/system/cpu/cpu0/cpufreq/scaling_governor','schedutil');write(tmp_path,'sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors','powersave schedutil');write(tmp_path,'sys/class/thermal/thermal_zone0/temp','55000');(tmp_path/'dev').mkdir();(tmp_path/'dev/watchdog0').touch();(tmp_path/'sys/firmware/efi').mkdir(parents=True)
 r=PowerDetector(root=tmp_path).detect();assert r.temperatures_celsius==(55.0,) and r.uefi

def test_missing_sysfs_safe(tmp_path): assert PowerDetector(root=tmp_path).detect().governors==()
def test_profile(project_root): assert load_power_profile(project_root/'config/power.yaml')['profile']=='wyse3040'
@pytest.mark.parametrize('text',['[]\n','schema_version: 2\n','schema_version: 1\nprofile: x\n'])
def test_invalid_profile(tmp_path,text):
 p=tmp_path/'p.yaml';p.write_text(text)
 with pytest.raises(PowerThermalError):load_power_profile(p)
def test_invalid_thresholds(tmp_path,project_root):
 import yaml;p=load_power_profile(project_root/'config/power.yaml');p['thermal']['warning_celsius']=95;f=tmp_path/'p.yaml';f.write_text(yaml.safe_dump(p))
 with pytest.raises(PowerThermalError):load_power_profile(f)
def test_compatible(project_root): assert compare_power(inv(),load_power_profile(project_root/'config/power.yaml')).compatible
def test_bad_governor_fails(project_root): assert not compare_power(inv(governors=('performance',)),load_power_profile(project_root/'config/power.yaml')).compatible
def test_critical_temperature_fails(project_root): assert not compare_power(inv(temperatures_celsius=(95.0,)),load_power_profile(project_root/'config/power.yaml')).compatible
def test_warning_temperature_warns(project_root):
 r=compare_power(inv(temperatures_celsius=(85.0,)),load_power_profile(project_root/'config/power.yaml'));assert r.compatible and any(c.status=='warning' for c in r.checks)
def test_missing_watchdog_warns(project_root): assert compare_power(inv(watchdog_devices=()),load_power_profile(project_root/'config/power.yaml')).compatible
def test_missing_uefi_fails(project_root): assert not compare_power(inv(uefi=False),load_power_profile(project_root/'config/power.yaml')).compatible
def test_plan_and_execute(tmp_path,project_root):
 p=create_power_configuration_plan(tmp_path/'build/rootfs',project_root/'config/power.yaml');assert 'lm-sensors' in p.packages;assert PowerConfigurator().execute(p,dry_run=True)==();w=PowerConfigurator().execute(p);assert len(w)==5 and 'AllowSuspend=no' in w[0].read_text()
def test_unsafe_rootfs(project_root):
 with pytest.raises(PowerThermalError):create_power_configuration_plan(Path('/'),project_root/'config/power.yaml')
def test_symlink(tmp_path,project_root):
 p=create_power_configuration_plan(tmp_path/'build/rootfs',project_root/'config/power.yaml');t=p.rootfs/'etc/xaac/power-policy.json';t.parent.mkdir(parents=True);t.symlink_to(tmp_path/'x')
 with pytest.raises(PowerThermalError):PowerConfigurator().execute(p)
def test_report(tmp_path,project_root):
 r=compare_power(inv(),load_power_profile(project_root/'config/power.yaml'));d=tmp_path/'r.json';write_power_report(r,d);assert json.loads(d.read_text())['compatible']
def test_cli_parser(project_root):
 from xaac_thin_client_os.cli import build_parser
 assert build_parser().parse_args(['--root',str(project_root),'configure-power','--dry-run']).command=='configure-power'
def test_cli_inspect(monkeypatch,project_root,capsys):
 from xaac_thin_client_os.cli import main
 monkeypatch.setattr('xaac_thin_client_os.cli.PowerDetector.detect',lambda self:inv());assert main(['--root',str(project_root),'--json','inspect-power'])==0;assert json.loads(capsys.readouterr().out)['compatible']
