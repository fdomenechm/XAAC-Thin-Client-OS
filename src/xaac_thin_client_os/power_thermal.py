"""Power, thermal and watchdog support for Dell Wyse 3040."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class PowerThermalError(RuntimeError): pass

@dataclass(frozen=True, slots=True)
class PowerInventory:
    governors: tuple[str, ...]
    available_governors: tuple[str, ...]
    temperatures_celsius: tuple[float, ...]
    watchdog_devices: tuple[str, ...]
    uefi: bool
    def to_dict(self):
        return {"governors": list(self.governors), "available_governors": list(self.available_governors), "temperatures_celsius": list(self.temperatures_celsius), "watchdog_devices": list(self.watchdog_devices), "uefi": self.uefi}

@dataclass(frozen=True, slots=True)
class PowerCheck:
    name: str; status: str; expected: str; actual: str
    def to_dict(self): return {"name":self.name,"status":self.status,"expected":self.expected,"actual":self.actual}

@dataclass(frozen=True, slots=True)
class PowerReport:
    profile: str; compatible: bool; inventory: PowerInventory; checks: tuple[PowerCheck,...]
    def to_dict(self): return {"profile":self.profile,"compatible":self.compatible,"inventory":self.inventory.to_dict(),"checks":[c.to_dict() for c in self.checks]}

class PowerDetector:
    def __init__(self, *, root: Path=Path('/')): self.root=root
    @staticmethod
    def _read(path: Path, default=''):
        try: return path.read_text(encoding='utf-8', errors='replace').strip()
        except OSError: return default
    def detect(self)->PowerInventory:
        cpu=self.root/'sys/devices/system/cpu'
        gov=[]; avail=set()
        for p in sorted(cpu.glob('cpu[0-9]*/cpufreq/scaling_governor')): gov.append(self._read(p))
        for p in sorted(cpu.glob('cpu[0-9]*/cpufreq/scaling_available_governors')): avail.update(self._read(p).split())
        temps=[]
        for p in sorted((self.root/'sys/class/thermal').glob('thermal_zone*/temp')):
            raw=self._read(p)
            try:
                value=float(raw); temps.append(value/1000 if value>1000 else value)
            except ValueError: pass
        watchdogs=tuple(sorted(p.name for p in (self.root/'dev').glob('watchdog*')))
        return PowerInventory(tuple(g for g in gov if g), tuple(sorted(avail)), tuple(temps), watchdogs, (self.root/'sys/firmware/efi').exists())

def load_power_profile(path: Path)->dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise PowerThermalError(f"No s'ha pogut carregar el perfil d'energia: {exc}") from exc
    required=('cpu','thermal','suspend','watchdog','power_loss','configuration')
    if not isinstance(raw,dict) or raw.get('schema_version')!=1 or not isinstance(raw.get('profile'),str) or any(not isinstance(raw.get(k),dict) for k in required) or not isinstance(raw.get('packages'),list): raise PowerThermalError('Perfil d’energia invàlid o esquema no suportat')
    if int(raw['thermal'].get('warning_celsius',0)) >= int(raw['thermal'].get('critical_celsius',0)): raise PowerThermalError('Llindars tèrmics invàlids')
    return raw

def compare_power(inv:PowerInventory, profile:dict[str,Any])->PowerReport:
    checks=[]
    def add(n,ok,e,a,warning=False): checks.append(PowerCheck(n,'pass' if ok else ('warning' if warning else 'fail'),str(e),str(a)))
    accepted=set(profile['cpu'].get('accepted_governors',[])); active=set(inv.governors)
    add('cpu-governor', bool(active) and active<=accepted, sorted(accepted), sorted(active) or 'absent')
    require_sensor=bool(profile['thermal'].get('require_sensor',True)); add('thermal-sensor',bool(inv.temperatures_celsius),'present',inv.temperatures_celsius or 'absent',warning=not require_sensor)
    critical=float(profile['thermal']['critical_celsius']); maximum=max(inv.temperatures_celsius) if inv.temperatures_celsius else None
    add('temperature-critical', maximum is None or maximum<critical, f'<{critical}', maximum if maximum is not None else 'unknown')
    warning=float(profile['thermal']['warning_celsius']); add('temperature-warning', maximum is None or maximum<warning, f'<{warning}', maximum if maximum is not None else 'unknown',warning=True)
    required=bool(profile['watchdog'].get('required',False)); add('watchdog',bool(inv.watchdog_devices),'present',inv.watchdog_devices or 'absent',warning=not required)
    add('uefi',inv.uefi,True,inv.uefi)
    return PowerReport(str(profile['profile']), not any(c.status=='fail' for c in checks), inv, tuple(checks))

@dataclass(frozen=True, slots=True)
class PowerConfigurationPlan:
    rootfs:Path; files:tuple[tuple[PurePosixPath,str,int],...]; packages:tuple[str,...]
    def to_manifest(self): return {'files':[str(x[0]) for x in self.files],'packages':list(self.packages)}

def create_power_configuration_plan(rootfs:Path, profile_path:Path)->PowerConfigurationPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.parent==Path('/'): raise PowerThermalError(f'Rootfs insegur: {root}')
    p=load_power_profile(profile_path); c=p['configuration']
    policy=json.dumps({'preferred_governor':p['cpu']['preferred_governor'],'allow_suspend':p['suspend']['allow_suspend'],'allow_hibernate':p['suspend']['allow_hibernate'],'thermal':p['thermal'],'watchdog':p['watchdog'],'power_loss':p['power_loss']},ensure_ascii=False,indent=2,sort_keys=True)+'\n'
    files=((PurePosixPath(c['systemd_sleep_file']), '[Sleep]\nAllowSuspend=no\nAllowHibernation=no\nAllowHybridSleep=no\nAllowSuspendThenHibernate=no\n',0o644),(PurePosixPath(c['systemd_system_file']),f"[Manager]\nRuntimeWatchdogSec={int(p['watchdog']['timeout_seconds'])}s\n",0o644),(PurePosixPath(c['sysctl_file']),'kernel.watchdog = 1\n',0o644),(PurePosixPath(c['tmpfiles_file']),'d /run/xaac 0755 root root -\n',0o644),(PurePosixPath(c['policy_file']),policy,0o644))
    return PowerConfigurationPlan(root,files,tuple(str(x) for x in p['packages']))

class PowerConfigurator:
    def execute(self, plan:PowerConfigurationPlan, *, dry_run=False):
        if dry_run:return ()
        out=[]
        for rel,content,mode in plan.files:
            target=plan.rootfs/str(rel).lstrip('/')
            if target.is_symlink(): raise PowerThermalError(f"No s'escriu sobre un enllaç simbòlic: {target}")
            target.parent.mkdir(parents=True,exist_ok=True); temp=target.with_name(target.name+'.tmp'); temp.write_text(content,encoding='utf-8'); temp.chmod(mode); temp.replace(target); out.append(target)
        return tuple(out)

def write_power_report(report:PowerReport,destination:Path)->None:
    if destination.is_symlink(): raise PowerThermalError(f"No s'escriu sobre un enllaç simbòlic: {destination}")
    destination.parent.mkdir(parents=True,exist_ok=True); temp=destination.with_suffix(destination.suffix+'.tmp'); temp.write_text(json.dumps(report.to_dict(),ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8'); temp.replace(destination)
