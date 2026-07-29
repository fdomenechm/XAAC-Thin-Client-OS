"""Staged update verification policy (phase 10.4)."""
from __future__ import annotations
import json, os, re, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class UpdateVerificationError(RuntimeError):
    """Raised when update verification policy is unsafe or inconsistent."""

_SEMVER=re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
def _path(value:object, field:str)->str:
    if not isinstance(value,str) or not value.startswith('/') or '..' in PurePosixPath(value).parts:
        raise UpdateVerificationError(f"Ruta insegura en {field}")
    return value
def load_update_verification(path:Path)->dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise UpdateVerificationError(f"No s'ha pogut carregar la verificació: {exc}") from exc
    if not isinstance(raw,dict) or raw.get('schema_version')!=1 or raw.get('hardware_profile')!='wyse3040': raise UpdateVerificationError('Política de verificació invàlida')
    if not isinstance(raw.get('verification_id'),str) or not raw['verification_id'].strip(): raise UpdateVerificationError('verification_id invàlid')
    staging=raw.get('staging')
    if not isinstance(staging,dict): raise UpdateVerificationError('Staging absent')
    staging['root']=_path(staging.get('root'),'staging.root')
    if not isinstance(staging.get('manifest_name'),str) or '/' in staging['manifest_name'] or not staging['manifest_name'].endswith('.json'): raise UpdateVerificationError('Nom de manifest invàlid')
    trust=raw.get('trust')
    if not isinstance(trust,dict) or trust.get('require_signature') is not True: raise UpdateVerificationError('La signatura ha de ser obligatòria')
    trust['keyring']=_path(trust.get('keyring'),'trust.keyring')
    if not isinstance(trust.get('signature_file'),str) or '/' in trust['signature_file']: raise UpdateVerificationError('Fitxer de signatura invàlid')
    hashes=raw.get('hashes')
    if not isinstance(hashes,dict) or hashes.get('require_all') is not True: raise UpdateVerificationError('Política de hashes invàlida')
    algorithms=hashes.get('algorithms')
    if not isinstance(algorithms,list) or set(algorithms)!={'sha256','sha512'} or len(algorithms)!=2: raise UpdateVerificationError('Algorismes de hash invàlids')
    compat=raw.get('compatibility')
    if not isinstance(compat,dict) or compat.get('architecture')!='amd64' or compat.get('os_id')!='xaac-thin-client-os' or compat.get('require_hardware_profile') is not True or compat.get('allow_downgrade') is not False: raise UpdateVerificationError('Compatibilitat invàlida')
    version=compat.get('minimum_installed_version')
    if not isinstance(version,str) or not _SEMVER.fullmatch(version): raise UpdateVerificationError('Versió mínima invàlida')
    deps=raw.get('dependencies')
    if not isinstance(deps,dict) or any(deps.get(k) is not True for k in ('require_declared','reject_cycles','require_atomic_sets')): raise UpdateVerificationError('Política de dependències invàlida')
    outputs=raw.get('outputs'); required={'policy','state','verifier'}
    if not isinstance(outputs,dict) or set(outputs)!=required: raise UpdateVerificationError('outputs incomplet')
    raw['outputs']={k:_path(v,f'outputs.{k}') for k,v in outputs.items()}
    return raw

@dataclass(frozen=True,slots=True)
class UpdateVerificationPlan:
    rootfs:Path; profile:dict[str,Any]
    def output(self,key:str)->Path:return self.rootfs/self.profile['outputs'][key].lstrip('/')
    def manifest(self)->dict[str,object]:return {'schema_version':1,'verification_id':self.profile['verification_id'],'hardware_profile':self.profile['hardware_profile'],'algorithms':self.profile['hashes']['algorithms'],'minimum_installed_version':self.profile['compatibility']['minimum_installed_version']}
def create_update_verification_plan(rootfs:Path,profile_path:Path)->UpdateVerificationPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise UpdateVerificationError(f'Rootfs insegur: {root}')
    return UpdateVerificationPlan(root,load_update_verification(profile_path))
class UpdateVerificationInstaller:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise UpdateVerificationError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def install(self,plan:UpdateVerificationPlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=tuple(plan.output(k) for k in ('policy','state','verifier'))
        if dry_run:return targets
        policy={k:v for k,v in plan.profile.items() if k!='outputs'}
        state={**plan.manifest(),'status':'idle','verified_version':None,'verified_at':None,'checks':{'signature':None,'hashes':None,'compatibility':None,'dependencies':None},'last_error':None}
        verifier='''#!/bin/sh\nset -eu\nPOLICY=/etc/xaac/update/verification.json\nSTATE=/var/lib/xaac-update/verification-state.json\n[ -r "$POLICY" ] || { echo "missing verification policy" >&2; exit 2; }\n[ -r "$STATE" ] || { echo "missing verification state" >&2; exit 2; }\nexec /usr/bin/xaac-update-service verify-staged "$@"\n'''
        self._write(targets[0],json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640)
        self._write(targets[1],json.dumps(state,indent=2,sort_keys=True)+'\n',0o640)
        self._write(targets[2],verifier,0o750)
        return targets
