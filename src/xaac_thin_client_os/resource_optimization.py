"""RAM and storage optimisation for resource-constrained thin clients."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class ResourceOptimizationError(RuntimeError): pass

@dataclass(frozen=True, slots=True)
class ResourceInventory:
    total_memory_mib: int
    available_memory_mib: int
    swap_total_mib: int
    zram_devices: tuple[str, ...]
    root_free_mib: int
    root_mount_options: tuple[str, ...]
    journald_persistent: bool
    def to_dict(self):
        return {"total_memory_mib":self.total_memory_mib,"available_memory_mib":self.available_memory_mib,"swap_total_mib":self.swap_total_mib,"zram_devices":list(self.zram_devices),"root_free_mib":self.root_free_mib,"root_mount_options":list(self.root_mount_options),"journald_persistent":self.journald_persistent}

@dataclass(frozen=True, slots=True)
class ResourceCheck:
    name:str; status:str; expected:str; actual:str
    def to_dict(self): return {"name":self.name,"status":self.status,"expected":self.expected,"actual":self.actual}

@dataclass(frozen=True, slots=True)
class ResourceReport:
    profile:str; compatible:bool; inventory:ResourceInventory; checks:tuple[ResourceCheck,...]
    def to_dict(self): return {"profile":self.profile,"compatible":self.compatible,"inventory":self.inventory.to_dict(),"checks":[c.to_dict() for c in self.checks]}

class ResourceDetector:
    def __init__(self, *, root:Path=Path('/')): self.root=root
    @staticmethod
    def _read(path:Path, default=''):
        try:return path.read_text(encoding='utf-8',errors='replace')
        except OSError:return default
    def detect(self)->ResourceInventory:
        values={}
        for line in self._read(self.root/'proc/meminfo').splitlines():
            if ':' in line:
                key,val=line.split(':',1)
                try: values[key]=int(val.strip().split()[0])//1024
                except (ValueError,IndexError): pass
        zram=tuple(sorted(p.name for p in (self.root/'sys/block').glob('zram*')))
        free=0
        stat=self.root/'__root_statvfs__'
        if stat.exists():
            try: free=int(self._read(stat).strip())
            except ValueError: pass
        elif self.root==Path('/'):
            try:
                s=(self.root).statvfs();free=(s.f_bavail*s.f_frsize)//(1024*1024)
            except OSError: pass
        options=()
        for line in self._read(self.root/'proc/mounts').splitlines():
            parts=line.split()
            if len(parts)>=4 and parts[1]=='/': options=tuple(parts[3].split(','));break
        persistent=(self.root/'var/log/journal').exists()
        return ResourceInventory(values.get('MemTotal',0),values.get('MemAvailable',0),values.get('SwapTotal',0),zram,free,options,persistent)

def load_resource_profile(path:Path)->dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise ResourceOptimizationError(f"No s'ha pogut carregar el perfil de recursos: {exc}") from exc
    required=('memory','storage','journald','tmpfs','cleanup','services','configuration')
    if not isinstance(raw,dict) or raw.get('schema_version')!=1 or not isinstance(raw.get('profile'),str) or any(not isinstance(raw.get(k),dict) for k in required) or not isinstance(raw.get('packages'),list): raise ResourceOptimizationError('Perfil de recursos invàlid o esquema no suportat')
    percent=int(raw['memory'].get('zram',{}).get('size_percent',0))
    if percent<10 or percent>100: raise ResourceOptimizationError('Percentatge de zram invàlid')
    if int(raw['journald'].get('runtime_max_use_mib',0))<=0: raise ResourceOptimizationError('Límit de journald invàlid')
    return raw

def compare_resources(inv:ResourceInventory, profile:dict[str,Any])->ResourceReport:
    checks=[]
    def add(n,ok,e,a,warning=False): checks.append(ResourceCheck(n,'pass' if ok else ('warning' if warning else 'fail'),str(e),str(a)))
    minimum=int(profile['memory']['minimum_total_mib']);add('memory-total',inv.total_memory_mib>=minimum,f'>={minimum} MiB',f'{inv.total_memory_mib} MiB')
    zreq=bool(profile['memory']['zram']['enabled']);add('zram',bool(inv.zram_devices) or not zreq,'present' if zreq else 'optional',inv.zram_devices or 'absent',warning=True)
    free=int(profile['storage']['root_minimum_free_mib']);add('root-free-space',inv.root_free_mib>=free,f'>={free} MiB',f'{inv.root_free_mib} MiB',warning=True)
    noatime=not profile['storage'].get('require_noatime',True) or 'noatime' in inv.root_mount_options;add('root-noatime',noatime,'noatime',inv.root_mount_options or 'unknown',warning=True)
    volatile=profile['journald'].get('storage')=='volatile';add('journald-storage',not(volatile and inv.journald_persistent),'volatile','persistent' if inv.journald_persistent else 'volatile',warning=True)
    return ResourceReport(str(profile['profile']),not any(c.status=='fail' for c in checks),inv,tuple(checks))

@dataclass(frozen=True, slots=True)
class ResourceConfigurationPlan:
    rootfs:Path; files:tuple[tuple[PurePosixPath,str,int],...]; disabled_services:tuple[str,...]; packages:tuple[str,...]
    def to_manifest(self): return {'files':[str(f[0]) for f in self.files],'disabled_services':list(self.disabled_services),'packages':list(self.packages)}

def create_resource_configuration_plan(rootfs:Path, profile_path:Path)->ResourceConfigurationPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.parent==Path('/'): raise ResourceOptimizationError(f'Rootfs insegur: {root}')
    p=load_resource_profile(profile_path);c=p['configuration'];z=p['memory']['zram'];j=p['journald'];t=p['tmpfs'];cl=p['cleanup']
    policy=json.dumps({k:p[k] for k in ('memory','storage','journald','tmpfs','cleanup','services')},ensure_ascii=False,indent=2,sort_keys=True)+'\n'
    files=(
      (PurePosixPath(c['zram_generator_file']),f"[zram0]\nzram-size = ram * {int(z['size_percent'])} / 100\ncompression-algorithm = {z['algorithm']}\nswap-priority = {int(z['priority'])}\n",0o644),
      (PurePosixPath(c['sysctl_file']),f"vm.swappiness = {int(p['memory']['swappiness'])}\nvm.page-cluster = 0\nvm.vfs_cache_pressure = 100\n",0o644),
      (PurePosixPath(c['journald_file']),f"[Journal]\nStorage={str(j['storage']).capitalize()}\nRuntimeMaxUse={int(j['runtime_max_use_mib'])}M\nRuntimeKeepFree={int(j['runtime_keep_free_mib'])}M\nMaxFileSec={j['max_file_sec']}\nCompress=yes\n",0o644),
      (PurePosixPath(c['tmp_mount_file']),f"[Mount]\nOptions=mode=1777,strictatime,nosuid,nodev,size={int(t['tmp_size_mib'])}M\n",0o644),
      (PurePosixPath(c['fstab_dropin']),'# Apply noatime to persistent filesystems during image assembly.\nrootfs / ext4 defaults,noatime,errors=remount-ro 0 1\n',0o644),
      (PurePosixPath(c['tmpfiles_file']),f"D /tmp 1777 root root {int(cl['age_days'])}d\nD /var/tmp 1777 root root {int(cl['age_days'])}d\n",0o644),
      (PurePosixPath(c['policy_file']),policy,0o644),
    )
    return ResourceConfigurationPlan(root,files,tuple(str(x) for x in p['services']['disabled']),tuple(str(x) for x in p['packages']))

class ResourceConfigurator:
    def execute(self,plan:ResourceConfigurationPlan,*,dry_run=False):
        if dry_run:return ()
        out=[]
        for rel,content,mode in plan.files:
            target=plan.rootfs/str(rel).lstrip('/')
            if target.is_symlink(): raise ResourceOptimizationError(f"No s'escriu sobre un enllaç simbòlic: {target}")
            target.parent.mkdir(parents=True,exist_ok=True);tmp=target.with_name(target.name+'.tmp');tmp.write_text(content,encoding='utf-8');tmp.chmod(mode);tmp.replace(target);out.append(target)
        wants=plan.rootfs/'etc/systemd/system'
        wants.mkdir(parents=True,exist_ok=True)
        for service in plan.disabled_services:
            target=wants/service
            if target.exists() and not target.is_symlink(): raise ResourceOptimizationError(f'Ruta systemd conflictiva: {target}')
            if not target.exists(): target.symlink_to('/dev/null')
            out.append(target)
        return tuple(out)

def write_resource_report(report:ResourceReport,destination:Path)->None:
    if destination.is_symlink(): raise ResourceOptimizationError(f"No s'escriu sobre un enllaç simbòlic: {destination}")
    destination.parent.mkdir(parents=True,exist_ok=True);tmp=destination.with_suffix(destination.suffix+'.tmp');tmp.write_text(json.dumps(report.to_dict(),ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8');tmp.replace(destination)
