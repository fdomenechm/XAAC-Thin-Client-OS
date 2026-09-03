"""Declarative kernel hardening policy for the production appliance."""
from __future__ import annotations
import json, os, re, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class KernelHardeningError(RuntimeError): pass
_KEY=re.compile(r"[a-z0-9_.]+\Z")
_MOD=re.compile(r"[A-Za-z0-9_-]+\Z")

def _path(v: object, field: str)->str:
    if not isinstance(v,str) or not v.startswith('/') or '..' in PurePosixPath(v).parts:
        raise KernelHardeningError(f"Ruta insegura en {field}")
    return v

def load_kernel_hardening_policy(path:Path)->dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as e: raise KernelHardeningError(f"No s'ha pogut carregar la política: {e}") from e
    if not isinstance(raw,dict) or raw.get('schema_version')!=1: raise KernelHardeningError('Política de kernel invàlida')
    if not isinstance(raw.get('policy_id'),str) or not raw['policy_id']: raise KernelHardeningError('policy_id és obligatori')
    sysctl=raw.get('sysctl')
    if not isinstance(sysctl,dict) or not sysctl: raise KernelHardeningError('sysctl ha de ser un mapa no buit')
    for k,v in sysctl.items():
        if not isinstance(k,str) or not _KEY.fullmatch(k) or not isinstance(v,(int,str)): raise KernelHardeningError(f'Paràmetre sysctl invàlid: {k}')
    required={'kernel.randomize_va_space':2,'kernel.yama.ptrace_scope':2,'kernel.sysrq':0,'fs.suid_dumpable':0,'net.ipv4.ip_forward':0}
    if any(sysctl.get(k)!=v for k,v in required.items()): raise KernelHardeningError('Controls obligatoris de kernel incomplets')
    mp=raw.get('module_policy')
    if not isinstance(mp,dict) or set(mp)!={'disabled','allowed_runtime'}: raise KernelHardeningError('module_policy incompleta')
    for key in mp:
        if not isinstance(mp[key],list) or not all(isinstance(x,str) and _MOD.fullmatch(x) for x in mp[key]): raise KernelHardeningError(f'Mòduls invàlids en {key}')
        if len(mp[key])!=len(set(mp[key])): raise KernelHardeningError(f'Mòduls duplicats en {key}')
    if set(mp['disabled']) & set(mp['allowed_runtime']): raise KernelHardeningError('Un mòdul no pot estar permés i deshabilitat')
    out=raw.get('outputs')
    if not isinstance(out,dict) or set(out)!={'sysctl','modules','limits','policy','state'}: raise KernelHardeningError('outputs incomplet')
    raw['outputs']={k:_path(v,f'outputs.{k}') for k,v in out.items()}
    return raw

@dataclass(frozen=True,slots=True)
class KernelHardeningPlan:
    rootfs:Path; profile:dict[str,Any]
    def destination(self,key:str)->Path:return self.rootfs/self.profile['outputs'][key].lstrip('/')
    def manifest(self)->dict[str,object]:
        return {'schema_version':1,'policy_id':self.profile['policy_id'],'sysctl_count':len(self.profile['sysctl']),'disabled_module_count':len(self.profile['module_policy']['disabled'])}

def create_kernel_hardening_plan(rootfs:Path,profile_path:Path)->KernelHardeningPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise KernelHardeningError(f'Rootfs insegur: {root}')
    return KernelHardeningPlan(root,load_kernel_hardening_policy(profile_path))

class KernelHardeningInstaller:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise KernelHardeningError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def install(self,plan:KernelHardeningPlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=tuple(plan.destination(k) for k in ('sysctl','modules','limits','policy','state'))
        if dry_run:return targets
        p=plan.profile
        sysctl='# Managed by XAAC Thin Client OS — Bloc 9 / phase 9.2\n'+''.join(f'{k} = {v}\n' for k,v in sorted(p['sysctl'].items()))
        modules='# Managed by XAAC Thin Client OS — Bloc 9 / phase 9.2\n'+''.join(f'install {m} /bin/false\nblacklist {m}\n' for m in sorted(p['module_policy']['disabled']))
        limits='# Disable core dumps for all users\n* hard core 0\n* soft core 0\nroot hard core 0\nroot soft core 0\n'
        policy={k:v for k,v in p.items() if k!='outputs'}; state={**plan.manifest(),'status':'installed','aslr':True,'ptrace_restricted':True,'core_dumps_disabled':True,'magic_sysrq_disabled':True}
        self._write(plan.destination('sysctl'),sysctl,0o644); self._write(plan.destination('modules'),modules,0o644); self._write(plan.destination('limits'),limits,0o644)
        self._write(plan.destination('policy'),json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640); self._write(plan.destination('state'),json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640)
        return targets
