"""Transactional update installation policy (phase 10.5)."""
from __future__ import annotations
import json, os, re, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class TransactionalUpdateError(RuntimeError):
    """Raised when transactional installation policy is unsafe."""

_UNIT=re.compile(r"^[A-Za-z0-9@_.-]+\.service$")
def _path(value:object, field:str)->str:
    if not isinstance(value,str) or not value.startswith('/') or '..' in PurePosixPath(value).parts:
        raise TransactionalUpdateError(f"Ruta insegura en {field}")
    return value

def load_transactional_update(path:Path)->dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise TransactionalUpdateError(f"No s'ha pogut carregar la instal·lació transaccional: {exc}") from exc
    if not isinstance(raw,dict) or raw.get('schema_version')!=1 or raw.get('hardware_profile')!='wyse3040':
        raise TransactionalUpdateError('Política transaccional invàlida')
    if not isinstance(raw.get('transaction_id'),str) or not raw['transaction_id'].strip():
        raise TransactionalUpdateError('transaction_id invàlid')
    pre=raw.get('recovery_point')
    if not isinstance(pre,dict) or pre.get('required') is not True or pre.get('include_package_state') is not True or pre.get('include_configuration') is not True:
        raise TransactionalUpdateError('Punt de recuperació insuficient')
    pre['root']=_path(pre.get('root'),'recovery_point.root')
    install=raw.get('installation')
    if not isinstance(install,dict) or install.get('require_verified_staging') is not True or install.get('atomic_component_sets') is not True or install.get('noninteractive') is not True:
        raise TransactionalUpdateError('Instal·lació insegura')
    if not isinstance(install.get('lock_timeout_seconds'),int) or not 1<=install['lock_timeout_seconds']<=3600:
        raise TransactionalUpdateError('Timeout de bloqueig invàlid')
    services=raw.get('services')
    if not isinstance(services,dict) or services.get('restart_only_changed') is not True:
        raise TransactionalUpdateError('Política de serveis invàlida')
    units=services.get('allowed_units')
    if not isinstance(units,list) or not units or len(units)!=len(set(units)) or any(not isinstance(x,str) or not _UNIT.fullmatch(x) for x in units):
        raise TransactionalUpdateError('Unitats systemd invàlides')
    validation=raw.get('validation')
    required_checks={'packages','services','client_session','agent_health'}
    if not isinstance(validation,dict) or validation.get('required') is not True or validation.get('fail_closed') is not True or set(validation.get('checks',[]))!=required_checks:
        raise TransactionalUpdateError('Validació posterior invàlida')
    if not isinstance(validation.get('timeout_seconds'),int) or not 10<=validation['timeout_seconds']<=1800:
        raise TransactionalUpdateError('Timeout de validació invàlid')
    confirmation=raw.get('confirmation')
    if not isinstance(confirmation,dict) or confirmation.get('explicit') is not True or confirmation.get('remove_recovery_point_on_success') is not True:
        raise TransactionalUpdateError('Confirmació transaccional invàlida')
    failure=raw.get('failure')
    if not isinstance(failure,dict) or failure.get('mark_failed') is not True or failure.get('preserve_evidence') is not True or failure.get('automatic_rollback') is not True:
        raise TransactionalUpdateError('Gestió de fallada invàlida')
    outputs=raw.get('outputs'); required={'policy','state','installer','service'}
    if not isinstance(outputs,dict) or set(outputs)!=required:
        raise TransactionalUpdateError('outputs incomplet')
    raw['outputs']={k:_path(v,f'outputs.{k}') for k,v in outputs.items()}
    return raw

@dataclass(frozen=True,slots=True)
class TransactionalUpdatePlan:
    rootfs:Path; profile:dict[str,Any]
    def output(self,key:str)->Path:return self.rootfs/self.profile['outputs'][key].lstrip('/')
    def manifest(self)->dict[str,object]:
        return {'schema_version':1,'transaction_id':self.profile['transaction_id'],'hardware_profile':self.profile['hardware_profile'],'automatic_rollback':True,'validation_checks':self.profile['validation']['checks']}

def create_transactional_update_plan(rootfs:Path,profile_path:Path)->TransactionalUpdatePlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise TransactionalUpdateError(f'Rootfs insegur: {root}')
    return TransactionalUpdatePlan(root,load_transactional_update(profile_path))

class TransactionalUpdateInstaller:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise TransactionalUpdateError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def install(self,plan:TransactionalUpdatePlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=tuple(plan.output(k) for k in ('policy','state','installer','service'))
        if dry_run:return targets
        policy={k:v for k,v in plan.profile.items() if k!='outputs'}
        state={**plan.manifest(),'status':'idle','version':None,'recovery_point':None,'started_at':None,'completed_at':None,'confirmed_at':None,'changed_packages':[],'restarted_services':[],'checks':{},'last_error':None}
        installer='''#!/bin/sh\nset -eu\nPOLICY=/etc/xaac/update/transactional-installation.json\nVERIFY=/var/lib/xaac-update/verification-state.json\n[ -r "$POLICY" ] || { echo "missing transactional policy" >&2; exit 2; }\n[ -r "$VERIFY" ] || { echo "missing verification state" >&2; exit 2; }\nexec /usr/bin/xaac-update-service install-verified "$@"\n'''
        service='''[Unit]\nDescription=XAAC transactional update installation\nAfter=network-online.target xaac-update.service\nConditionPathExists=/var/lib/xaac-update/verification-state.json\n\n[Service]\nType=oneshot\nExecStart=/usr/libexec/xaac-update-install-transaction\nUser=root\nGroup=root\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=yes\nProtectSystem=strict\nReadWritePaths=/var/lib/xaac-update /var/cache/apt /var/lib/apt /var/lib/dpkg /etc/xaac\nLockPersonality=yes\nRestrictRealtime=yes\nUMask=0027\n'''
        self._write(targets[0],json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640)
        self._write(targets[1],json.dumps(state,indent=2,sort_keys=True)+'\n',0o640)
        self._write(targets[2],installer,0o750)
        self._write(targets[3],service,0o644)
        return targets
