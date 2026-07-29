"""Declarative AppArmor profiles for XAAC services (phase 9.4)."""
from __future__ import annotations
import json, os, re, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class AppArmorError(RuntimeError): pass
_NAME=re.compile(r"[A-Za-z0-9_.-]+\Z")
_TOKEN=re.compile(r"[a-z0-9_]+\Z")

def _path(v: object, field: str, glob: bool=False) -> str:
    if not isinstance(v,str) or not v.startswith('/') or '..' in PurePosixPath(v.replace('**','x')).parts:
        raise AppArmorError(f"Ruta insegura en {field}")
    if not glob and any(c in v for c in '*?[]{}'):
        raise AppArmorError(f"Ruta no literal en {field}")
    return v

def load_apparmor_policy(path: Path)->dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as e: raise AppArmorError(f"No s'ha pogut carregar la política: {e}") from e
    if not isinstance(raw,dict) or raw.get('schema_version')!=1: raise AppArmorError('Política AppArmor invàlida')
    if not isinstance(raw.get('policy_id'),str) or not raw['policy_id']: raise AppArmorError('policy_id és obligatori')
    d=raw.get('defaults')
    if not isinstance(d,dict) or any(d.get(k) is not True for k in ('attach_disconnected','mediate_deleted','audit_denied','deny_write_exec')):
        raise AppArmorError('Controls AppArmor obligatoris incomplets')
    profiles=raw.get('profiles')
    if not isinstance(profiles,list) or not profiles: raise AppArmorError('profiles ha de ser una llista no buida')
    names=set()
    for p in profiles:
        if not isinstance(p,dict) or not isinstance(p.get('name'),str) or not _NAME.fullmatch(p['name']): raise AppArmorError('Nom de perfil invàlid')
        if p['name'] in names: raise AppArmorError(f"Perfil duplicat: {p['name']}")
        names.add(p['name']); _path(p.get('executable'),f"{p['name']}.executable")
        if p.get('mode') not in {'complain','enforce'}: raise AppArmorError('Mode AppArmor invàlid')
        for key in ('abstractions','read_paths','write_paths','network','capabilities','signals'):
            if not isinstance(p.get(key),list): raise AppArmorError(f"{p['name']}.{key} ha de ser una llista")
        for key in ('read_paths','write_paths'):
            for v in p[key]: _path(v,f"{p['name']}.{key}",glob=True)
        for key in ('abstractions','network','capabilities','signals'):
            if not all(isinstance(v,str) and _TOKEN.fullmatch(v) for v in p[key]): raise AppArmorError(f"Token invàlid en {p['name']}.{key}")
    out=raw.get('outputs')
    if not isinstance(out,dict) or set(out)!={'profiles_root','complain_root','policy','state'}: raise AppArmorError('outputs incomplet')
    raw['outputs']={k:_path(v,f"outputs.{k}") for k,v in out.items()}
    return raw

@dataclass(frozen=True,slots=True)
class AppArmorPlan:
    rootfs: Path; profile: dict[str,Any]
    def destination(self,key:str)->Path: return self.rootfs/self.profile['outputs'][key].lstrip('/')
    def profile_path(self,name:str)->Path: return self.destination('profiles_root')/name
    def complain_link(self,name:str)->Path: return self.destination('complain_root')/name
    def manifest(self)->dict[str,object]:
        ps=self.profile['profiles']; return {'schema_version':1,'policy_id':self.profile['policy_id'],'profile_count':len(ps),'enforce_count':sum(p['mode']=='enforce' for p in ps),'complain_count':sum(p['mode']=='complain' for p in ps)}

def create_apparmor_plan(rootfs:Path, profile_path:Path)->AppArmorPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise AppArmorError(f'Rootfs insegur: {root}')
    return AppArmorPlan(root,load_apparmor_policy(profile_path))

class AppArmorInstaller:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise AppArmorError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    @staticmethod
    def _render(defaults:dict[str,Any],p:dict[str,Any])->str:
        flags=['attach_disconnected','mediate_deleted']; lines=[f"# Managed by XAAC Thin Client OS — phase 9.4",f"# mode: {p['mode']}"]
        lines += [f"#include <tunables/global>",f"profile {p['name']} {p['executable']} flags=({','.join(flags)}) {{"]
        lines += [f"  #include <abstractions/{x}>" for x in p['abstractions']]
        lines += [f"  {x} r," for x in p['read_paths']]+[f"  {x} rwk," for x in p['write_paths']]
        lines += [f"  network {x}," for x in p['network']]+[f"  capability {x}," for x in p['capabilities']]
        lines += [f"  signal ({','.join(p['signals'])}),"] if p['signals'] else []
        if defaults['deny_write_exec']: lines += ['  deny /tmp/** m,', '  deny /var/tmp/** m,', '  deny /run/user/** m,']
        lines += ['}']; return '\n'.join(lines)+'\n'
    def install(self,plan:AppArmorPlan,*,dry_run:bool=False)->tuple[Path,...]:
        ps=plan.profile['profiles']; profile_paths=tuple(plan.profile_path(p['name']) for p in ps); links=tuple(plan.complain_link(p['name']) for p in ps if p['mode']=='complain'); targets=profile_paths+links+(plan.destination('policy'),plan.destination('state'))
        if dry_run:return targets
        for p,target in zip(ps,profile_paths,strict=True): self._write(target,self._render(plan.profile['defaults'],p),0o644)
        for p in ps:
            link=plan.complain_link(p['name'])
            if p['mode']=='complain':
                link.parent.mkdir(parents=True,exist_ok=True)
                if link.exists() or link.is_symlink():
                    if not link.is_symlink() or os.readlink(link)!=f'../{p["name"]}': raise AppArmorError(f'Enllaç complain insegur: {link}')
                else: link.symlink_to(f'../{p["name"]}')
            elif link.is_symlink(): link.unlink()
        policy={k:v for k,v in plan.profile.items() if k!='outputs'}; state={**plan.manifest(),'status':'installed','audit_denied':True}
        self._write(plan.destination('policy'),json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640)
        self._write(plan.destination('state'),json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640)
        return targets
