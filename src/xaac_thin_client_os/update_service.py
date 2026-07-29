"""Update checking, download and staging service configuration (phase 10.3)."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class UpdateServiceError(RuntimeError):
    """Raised when the update service policy is unsafe or inconsistent."""

def _path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith('/') or '..' in PurePosixPath(value).parts:
        raise UpdateServiceError(f"Ruta insegura en {field}")
    return value

def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise UpdateServiceError(f"Valor invàlid en {field}")
    return value

def load_update_service(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        raise UpdateServiceError(f"No s'ha pogut carregar el servei: {exc}") from exc
    if not isinstance(raw, dict) or raw.get('schema_version') != 1 or raw.get('hardware_profile') != 'wyse3040':
        raise UpdateServiceError("Configuració del servei d'actualització invàlida")
    if not isinstance(raw.get('service_id'), str) or not raw['service_id'].strip():
        raise UpdateServiceError('service_id invàlid')
    schedule = raw.get('schedule')
    if not isinstance(schedule, dict) or schedule.get('respect_maintenance_window') is not True:
        raise UpdateServiceError('Planificació invàlida')
    _integer(schedule.get('check_interval_minutes'), 'schedule.check_interval_minutes', 5, 1440)
    _integer(schedule.get('jitter_seconds'), 'schedule.jitter_seconds', 0, 3600)
    repository = raw.get('repository')
    if not isinstance(repository, dict): raise UpdateServiceError('Repositori absent')
    for key in ('policy_path','update_model_path'): repository[key] = _path(repository.get(key), f'repository.{key}')
    storage = raw.get('storage')
    if not isinstance(storage, dict): raise UpdateServiceError('Emmagatzematge absent')
    for key in ('staging_root','state_path','lock_path'): storage[key] = _path(storage.get(key), f'storage.{key}')
    minimum = _integer(storage.get('minimum_free_bytes'), 'storage.minimum_free_bytes', 64*1024*1024, 4*1024**3)
    maximum = _integer(storage.get('maximum_download_bytes'), 'storage.maximum_download_bytes', minimum, 4*1024**3)
    if maximum < minimum: raise UpdateServiceError('Límit de descàrrega inferior a l’espai mínim')
    download = raw.get('download')
    if not isinstance(download, dict) or download.get('fsync') is not True: raise UpdateServiceError('Política de descàrrega invàlida')
    _integer(download.get('timeout_seconds'), 'download.timeout_seconds', 30, 7200)
    _integer(download.get('retries'), 'download.retries', 0, 10)
    suffix = download.get('partial_suffix')
    if not isinstance(suffix, str) or not suffix.startswith('.') or '/' in suffix: raise UpdateServiceError('Sufix parcial invàlid')
    state = raw.get('state')
    if not isinstance(state, dict) or not isinstance(state.get('transitions'), dict): raise UpdateServiceError('Model d’estats absent')
    transitions = state['transitions']; initial = state.get('initial'); known = set(transitions)
    if initial not in known: raise UpdateServiceError('Estat inicial invàlid')
    for source, targets in transitions.items():
        if not isinstance(targets, list) or source in targets or not set(targets) <= known: raise UpdateServiceError('Transició d’estat invàlida')
    reachable={initial}
    while True:
        expanded=reachable|{target for source in reachable for target in transitions[source]}
        if expanded==reachable: break
        reachable=expanded
    if reachable != known: raise UpdateServiceError('Hi ha estats inaccessibles')
    outputs=raw.get('outputs'); required={'policy','state','systemd_service','systemd_timer','tmpfiles'}
    if not isinstance(outputs, dict) or set(outputs)!=required: raise UpdateServiceError('outputs incomplet')
    raw['outputs']={key:_path(value,f'outputs.{key}') for key,value in outputs.items()}
    if raw['outputs']['state'] != storage['state_path']: raise UpdateServiceError('Rutes d’estat incoherents')
    return raw

@dataclass(frozen=True, slots=True)
class UpdateServicePlan:
    rootfs: Path
    profile: dict[str, Any]
    def output(self,key:str)->Path: return self.rootfs/self.profile['outputs'][key].lstrip('/')
    def manifest(self)->dict[str,object]:
        return {'schema_version':1,'service_id':self.profile['service_id'],'initial_state':self.profile['state']['initial'],'check_interval_minutes':self.profile['schedule']['check_interval_minutes']}

def create_update_service_plan(rootfs: Path, profile_path: Path)->UpdateServicePlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise UpdateServiceError(f'Rootfs insegur: {root}')
    return UpdateServicePlan(root,load_update_service(profile_path))

class UpdateServiceInstaller:
    @staticmethod
    def _write(path:Path, content:str, mode:int)->None:
        if path.is_symlink(): raise UpdateServiceError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream: stream.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def install(self,plan:UpdateServicePlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=tuple(plan.output(k) for k in ('policy','state','systemd_service','systemd_timer','tmpfiles'))
        if dry_run:return targets
        p=plan.profile
        policy={k:v for k,v in p.items() if k!='outputs'}
        state={**plan.manifest(),'status':p['state']['initial'],'available_version':None,'downloaded_bytes':0,'staging_path':None,'last_check':None,'last_error':None}
        service='''[Unit]\nDescription=XAAC controlled update service\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/xaac-update-service check-and-stage\nUser=root\nGroup=root\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectSystem=strict\nProtectHome=yes\nReadWritePaths=/var/lib/xaac-update /run/lock\nLockPersonality=yes\nRestrictSUIDSGID=yes\n\n[Install]\nWantedBy=multi-user.target\n'''
        interval=p['schedule']['check_interval_minutes']; jitter=p['schedule']['jitter_seconds']
        timer=f'''[Unit]\nDescription=Periodic XAAC update check\n\n[Timer]\nOnBootSec=5min\nOnUnitActiveSec={interval}min\nRandomizedDelaySec={jitter}\nPersistent=true\nUnit=xaac-update.service\n\n[Install]\nWantedBy=timers.target\n'''
        staging=p['storage']['staging_root']; state_dir=str(PurePosixPath(p['storage']['state_path']).parent)
        tmpfiles=f'd {state_dir} 0750 root root -\nd {staging} 0750 root root -\n'
        self._write(targets[0],json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640)
        self._write(targets[1],json.dumps(state,indent=2,sort_keys=True)+'\n',0o640)
        self._write(targets[2],service,0o644); self._write(targets[3],timer,0o644); self._write(targets[4],tmpfiles,0o644)
        return targets
