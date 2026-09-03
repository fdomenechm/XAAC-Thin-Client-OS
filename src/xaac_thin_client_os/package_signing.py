"""APT package signing trust policy (phase 9.7)."""
from __future__ import annotations
import json, os, re, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class PackageSigningError(RuntimeError): pass
_FP=re.compile(r"^[0-9A-F]{40}(?:[0-9A-F]{24})?$")

def _path(v:object,field:str)->str:
    if not isinstance(v,str) or not v.startswith('/') or '..' in PurePosixPath(v).parts:
        raise PackageSigningError(f"Ruta insegura en {field}")
    return v

def _fingerprint(v:object,field:str)->str:
    if not isinstance(v,str) or not _FP.fullmatch(v): raise PackageSigningError(f"Fingerprint invàlid en {field}")
    return v

def load_package_signing_policy(path:Path)->dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as e: raise PackageSigningError(f"No s'ha pogut carregar la política: {e}") from e
    if not isinstance(raw,dict) or raw.get('schema_version')!=1: raise PackageSigningError('Política de signatura invàlida')
    repo=raw.get('repository'); keys=raw.get('keys'); ver=raw.get('verification'); out=raw.get('outputs')
    if not isinstance(repo,dict) or not isinstance(keys,dict) or not isinstance(ver,dict): raise PackageSigningError('Seccions obligatòries absents')
    for k in ('name','suite','source_uri'):
        if not isinstance(repo.get(k),str) or not repo[k]: raise PackageSigningError(f'repository.{k} invàlid')
    if not repo['source_uri'].startswith('https://'): raise PackageSigningError('El repositori ha d’utilitzar HTTPS')
    repo['signed_by']=_path(repo.get('signed_by'),'repository.signed_by')
    comps=repo.get('components');
    if not isinstance(comps,list) or not comps or not all(isinstance(x,str) and x.isidentifier() for x in comps): raise PackageSigningError('Components invàlids')
    active=keys.get('active')
    if not isinstance(active,dict): raise PackageSigningError('Clau activa absent')
    active['fingerprint']=_fingerprint(active.get('fingerprint'),'keys.active.fingerprint'); active['public_key']=_path(active.get('public_key'),'keys.active.public_key')
    previous=keys.get('trusted_previous',[])
    if not isinstance(previous,list): raise PackageSigningError('trusted_previous invàlid')
    for i,item in enumerate(previous):
        if not isinstance(item,dict): raise PackageSigningError('Clau anterior invàlida')
        item['fingerprint']=_fingerprint(item.get('fingerprint'),f'keys.trusted_previous[{i}]'); item['public_key']=_path(item.get('public_key'),f'keys.trusted_previous[{i}].public_key')
    revoked=keys.get('revoked',[])
    if not isinstance(revoked,list): raise PackageSigningError('revoked invàlid')
    keys['revoked']=[_fingerprint(x,'keys.revoked') for x in revoked]
    trusted=[active['fingerprint'],*(x['fingerprint'] for x in previous)]
    if len(trusted)!=len(set(trusted)) or set(trusted)&set(keys['revoked']): raise PackageSigningError('Conflicte entre claus confiables i revocades')
    if not ver.get('require_signed_release') or ver.get('allow_weak_digest') is not False: raise PackageSigningError('La verificació no pot relaxar signatures o digests')
    if not isinstance(ver.get('offline_bundle_manifest'),str) or '/' in ver['offline_bundle_manifest']: raise PackageSigningError('Manifest offline invàlid')
    required={'policy','source','apt_conf','verifier','state'}
    if not isinstance(out,dict) or set(out)!=required: raise PackageSigningError('outputs incomplet')
    raw['outputs']={k:_path(v,f'outputs.{k}') for k,v in out.items()}
    return raw

@dataclass(frozen=True,slots=True)
class PackageSigningPlan:
    rootfs:Path; profile:dict[str,Any]
    def destination(self,p:str)->Path:return self.rootfs/p.lstrip('/')
    def output(self,k:str)->Path:return self.destination(self.profile['outputs'][k])
    def manifest(self)->dict[str,object]:
        return {'schema_version':1,'policy_id':self.profile['policy_id'],'active_fingerprint':self.profile['keys']['active']['fingerprint'],'trusted_key_count':1+len(self.profile['keys']['trusted_previous']),'revoked_key_count':len(self.profile['keys']['revoked'])}

def create_package_signing_plan(rootfs:Path,profile_path:Path)->PackageSigningPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise PackageSigningError(f'Rootfs insegur: {root}')
    return PackageSigningPlan(root,load_package_signing_policy(profile_path))

class PackageSigningInstaller:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise PackageSigningError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def install(self,plan:PackageSigningPlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=tuple(plan.output(k) for k in ('policy','source','apt_conf','verifier','state'))
        if dry_run:return targets
        p=plan.profile; r=p['repository']; v=p['verification']
        policy={k:x for k,x in p.items() if k!='outputs'}
        source=f"Types: deb\nURIs: {r['source_uri']}\nSuites: {r['suite']}\nComponents: {' '.join(r['components'])}\nSigned-By: {r['signed_by']}\n"
        apt='''Acquire::AllowInsecureRepositories "false";\nAcquire::AllowDowngradeToInsecureRepositories "false";\nAPT::Get::AllowUnauthenticated "false";\nAcquire::Check-Valid-Until "true";\n'''
        script=f'''#!/bin/sh\nset -eu\nbundle="${{1:?ús: verify-xaac-package-bundle DIRECTORI}}"\nmanifest="$bundle/{v['offline_bundle_manifest']}"\n[ -f "$manifest" ] || {{ echo "manifest absent" >&2; exit 3; }}\n[ -f "$manifest.asc" ] || {{ echo "signatura absent" >&2; exit 4; }}\ngpgv --keyring {r['signed_by']} "$manifest.asc" "$manifest"\n(cd "$bundle" && sha256sum -c "{v['offline_bundle_manifest']}")\n'''
        state={'schema_version':1,'status':'configured',**plan.manifest()}
        self._write(plan.output('policy'),json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o644)
        self._write(plan.output('source'),source,0o644); self._write(plan.output('apt_conf'),apt,0o644); self._write(plan.output('verifier'),script,0o750); self._write(plan.output('state'),json.dumps(state,indent=2,sort_keys=True)+'\n',0o640)
        return targets
