"""Transactional VLAN 802.1Q configuration for phase 7.4."""
from __future__ import annotations
import json, os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class VlanConfigurationError(RuntimeError): pass

def _abs(v: object, field: str) -> PurePosixPath:
    p=PurePosixPath(str(v))
    if not p.is_absolute() or '..' in p.parts: raise VlanConfigurationError(f"Ruta insegura: {field}")
    return p

def load_vlan_profile(path: Path) -> dict[str, Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise VlanConfigurationError(f"No s'ha pogut carregar el perfil: {exc}") from exc
    required={'schema_version','backend','allowed_sources','policy','paths'}
    if not isinstance(raw,dict) or set(raw)!=required or raw.get('schema_version')!=1: raise VlanConfigurationError('Esquema VLAN invàlid')
    if raw['backend']!='systemd-networkd' or raw['allowed_sources']!=['local','remote']: raise VlanConfigurationError('Backend o fonts VLAN no compatibles')
    pol=raw['policy']
    if set(pol)!={'minimum_id','maximum_id','maximum_vlans','parent_match','fallback_to_parent'} or not (1<=pol['minimum_id']<=pol['maximum_id']<=4094) or pol['maximum_vlans']<1: raise VlanConfigurationError('Política VLAN invàlida')
    if not isinstance(pol['parent_match'],str) or not pol['parent_match'] or not isinstance(pol['fallback_to_parent'],bool): raise VlanConfigurationError('Política VLAN invàlida')
    paths=raw['paths']; expected={'network_dir','state','snapshot','pending','diagnostics'}
    if not isinstance(paths,dict) or set(paths)!=expected: raise VlanConfigurationError('Rutes VLAN incompletes')
    for k,v in paths.items(): _abs(v,f'paths.{k}')
    return raw

@dataclass(frozen=True,slots=True)
class VlanRequest:
    source:str='local'; vlan_id:int=1; name:str|None=None; parent:str='en*'; mode:str='dhcp'; address:str|None=None; gateway:str|None=None; dns:tuple[str,...]=(); enabled:bool=True

@dataclass(frozen=True,slots=True)
class VlanPlan:
    rootfs:Path; profile:dict[str,Any]; request:VlanRequest; interface:str; files:dict[str,str]
    def path(self,name:str)->Path: return self.rootfs/_abs(self.profile['paths'][name],name).relative_to('/')
    def target(self,suffix:str)->Path: return self.path('network_dir')/f'30-xaac-{self.interface}.{suffix}'

def create_vlan_plan(rootfs:Path, profile_path:Path, request:VlanRequest)->VlanPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise VlanConfigurationError(f'Rootfs insegur: {root}')
    p=load_vlan_profile(profile_path); pol=p['policy']
    if request.source not in p['allowed_sources']: raise VlanConfigurationError('Font no autoritzada')
    if not pol['minimum_id']<=request.vlan_id<=pol['maximum_id']: raise VlanConfigurationError('Identificador VLAN fora de política')
    if request.mode not in {'dhcp','static'}: raise VlanConfigurationError('Mode VLAN invàlid')
    name=request.name or f'vlan{request.vlan_id}'
    if not name.replace('-','').replace('_','').isalnum() or len(name)>15: raise VlanConfigurationError('Nom VLAN invàlid')
    if request.parent!=pol['parent_match']: raise VlanConfigurationError('Interfície pare fora de política')
    if request.mode=='static' and not request.address: raise VlanConfigurationError('La VLAN estàtica requereix adreça')
    if request.mode=='dhcp' and (request.address or request.gateway): raise VlanConfigurationError('DHCP no admet adreça ni passarel·la')
    netdev=f"# Managed by XAAC Thin Client OS\n[NetDev]\nName={name}\nKind=vlan\n\n[VLAN]\nId={request.vlan_id}\n"
    parent=f"# Managed by XAAC Thin Client OS\n[Match]\nName={request.parent}\n\n[Network]\nVLAN={name}\n"
    network=["# Managed by XAAC Thin Client OS","[Match]",f"Name={name}","","[Network]"]
    if request.mode=='dhcp': network.append('DHCP=ipv4')
    else:
        network.append(f'Address={request.address}')
        if request.gateway: network.append(f'Gateway={request.gateway}')
        network += [f'DNS={d}' for d in request.dns]
    network += ['LinkLocalAddressing=ipv6','IPv6AcceptRA=no']
    return VlanPlan(root,p,request,name,{'netdev':netdev,'parent':parent,'network':'\n'.join(network)+'\n'})

class VlanManager:
    @staticmethod
    def _write(path:Path,content:str,mode:int=0o640)->None:
        if path.is_symlink(): raise VlanConfigurationError(f'No se sobreescriurà un enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name('.'+path.name+'.tmp'); tmp.write_text(content,encoding='utf-8'); tmp.chmod(mode); os.replace(tmp,path)
    def apply(self,plan:VlanPlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=(plan.target('netdev'),plan.target('parent.network'),plan.target('network')); state,snap,pending,diag=(plan.path(x) for x in ('state','snapshot','pending','diagnostics'))
        if dry_run:return (*targets,state,pending,diag)
        previous={str(t.relative_to(plan.rootfs)):t.read_text(encoding='utf-8') for t in targets if t.exists()}
        self._write(snap,json.dumps({'schema_version':1,'files':previous},indent=2,sort_keys=True)+'\n',0o600)
        self._write(pending,json.dumps({'schema_version':1,'status':'pending','vlan_id':plan.request.vlan_id},indent=2)+'\n',0o600)
        for t,c in zip(targets,plan.files.values()): self._write(t,c,0o644)
        payload={'schema_version':1,'status':'applied','source':plan.request.source,'vlan_id':plan.request.vlan_id,'interface':plan.interface,'parent':plan.request.parent,'mode':plan.request.mode,'fallback_to_parent':plan.profile['policy']['fallback_to_parent']}
        self._write(state,json.dumps(payload,indent=2,sort_keys=True)+'\n'); self._write(diag,json.dumps({'schema_version':1,'checks':['networkctl status '+plan.interface,'networkctl status'],'recovery':'rollback-or-parent'},indent=2)+'\n')
        pending.unlink(missing_ok=True); return (*targets,state,snap,diag)
    def rollback(self,plan:VlanPlan,*,dry_run:bool=False)->tuple[Path,...]:
        snap,state=plan.path('snapshot'),plan.path('state')
        targets=(plan.target('netdev'),plan.target('parent.network'),plan.target('network'))
        if not snap.exists(): raise VlanConfigurationError('No hi ha snapshot VLAN')
        data=json.loads(snap.read_text(encoding='utf-8')); files=data.get('files')
        if not isinstance(files,dict): raise VlanConfigurationError('Snapshot VLAN invàlid')
        if dry_run:return (*targets,state)
        for t in targets:
            key=str(t.relative_to(plan.rootfs))
            if key in files:self._write(t,files[key],0o644)
            else:t.unlink(missing_ok=True)
        self._write(state,json.dumps({'schema_version':1,'status':'rolled-back','fallback_to_parent':True},indent=2)+'\n'); return (*targets,state)
