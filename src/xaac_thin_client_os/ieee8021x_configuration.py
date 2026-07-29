"""Secure IEEE 802.1X wired configuration for phase 7.5."""
from __future__ import annotations
import json, os, re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class Ieee8021xError(RuntimeError): pass

def _abs(value: object, field: str) -> PurePosixPath:
    path=PurePosixPath(str(value))
    if not path.is_absolute() or '..' in path.parts: raise Ieee8021xError(f"Ruta insegura: {field}")
    return path

def load_ieee8021x_profile(path: Path)->dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise Ieee8021xError(f"No s'ha pogut carregar el perfil: {exc}") from exc
    if not isinstance(raw,dict) or set(raw)!={'schema_version','backend','allowed_sources','policy','paths'} or raw.get('schema_version')!=1: raise Ieee8021xError('Esquema IEEE 802.1X invàlid')
    if raw['backend']!='wpa_supplicant' or raw['allowed_sources']!=['local','remote']: raise Ieee8021xError('Backend o fonts IEEE 802.1X no compatibles')
    pol=raw['policy']
    if set(pol)!={'interface_match','allowed_eap','require_ca_certificate','maximum_identity_length'} or pol['allowed_eap']!=['tls','peap'] or pol['maximum_identity_length']<1: raise Ieee8021xError('Política IEEE 802.1X invàlida')
    expected={'supplicant','credentials','service','state','snapshot','pending','renewal','diagnostics'}
    if not isinstance(raw['paths'],dict) or set(raw['paths'])!=expected: raise Ieee8021xError('Rutes IEEE 802.1X incompletes')
    for key,value in raw['paths'].items(): _abs(value,f'paths.{key}')
    return raw

@dataclass(frozen=True,slots=True)
class Ieee8021xRequest:
    source:str='local'; interface:str='en*'; eap:str='tls'; identity:str=''; anonymous_identity:str|None=None
    ca_certificate:str|None=None; client_certificate:str|None=None; private_key:str|None=None
    private_key_password:str|None=None; password:str|None=None; enabled:bool=True

@dataclass(frozen=True,slots=True)
class Ieee8021xPlan:
    rootfs:Path; profile:dict[str,Any]; request:Ieee8021xRequest; files:dict[str,str]
    def path(self,name:str)->Path: return self.rootfs/_abs(self.profile['paths'][name],name).relative_to('/')

def _safe_text(value:str,field:str,maxlen:int=512)->str:
    if not value or len(value)>maxlen or any(c in value for c in '\n\r\0"'): raise Ieee8021xError(f'{field} invàlid')
    return value

def _cert_path(value:str|None,field:str,required:bool=False)->str|None:
    if required and not value: raise Ieee8021xError(f'{field} obligatori')
    if value:
        p=_abs(value,field)
        if not str(p).startswith('/etc/xaac/certificates/'): raise Ieee8021xError(f'{field} fora del directori autoritzat')
        return str(p)
    return None

def create_ieee8021x_plan(rootfs:Path,profile_path:Path,request:Ieee8021xRequest)->Ieee8021xPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise Ieee8021xError(f'Rootfs insegur: {root}')
    profile=load_ieee8021x_profile(profile_path); pol=profile['policy']
    if request.source not in profile['allowed_sources']: raise Ieee8021xError('Font no autoritzada')
    if request.interface!=pol['interface_match']: raise Ieee8021xError('Interfície fora de política')
    if request.eap not in pol['allowed_eap']: raise Ieee8021xError('Mètode EAP no autoritzat')
    identity=_safe_text(request.identity,'Identitat',pol['maximum_identity_length'])
    anonymous=_safe_text(request.anonymous_identity,'Identitat anònima',pol['maximum_identity_length']) if request.anonymous_identity else None
    ca=_cert_path(request.ca_certificate,'Certificat CA',pol['require_ca_certificate'])
    lines=['# Managed by XAAC Thin Client OS','ap_scan=0','network={','    key_mgmt=IEEE8021X',f'    eap={request.eap.upper()}',f'    identity="{identity}"']
    credentials=[]
    if ca: lines.append(f'    ca_cert="{ca}"')
    if anonymous: lines.append(f'    anonymous_identity="{anonymous}"')
    if request.eap=='tls':
        cert=_cert_path(request.client_certificate,'Certificat client',True); key=_cert_path(request.private_key,'Clau privada',True)
        lines += [f'    client_cert="{cert}"',f'    private_key="{key}"']
        if request.private_key_password:
            _safe_text(request.private_key_password,'Contrasenya de clau'); lines.append('    private_key_passwd="${PRIVATE_KEY_PASSWORD}"'); credentials.append('PRIVATE_KEY_PASSWORD='+request.private_key_password)
    else:
        if not request.password: raise Ieee8021xError('PEAP requereix contrasenya')
        _safe_text(request.password,'Contrasenya'); lines += ['    phase2="auth=MSCHAPV2"','    password="${PASSWORD}"']; credentials.append('PASSWORD='+request.password)
    lines.append('}')
    service='[Service]\nEnvironmentFile=-/etc/xaac/network/ieee8021x-credentials.env\nExecStart=\nExecStart=/sbin/wpa_supplicant -c/etc/wpa_supplicant/wpa_supplicant-xaac-wired.conf -D wired -i%i\n'
    return Ieee8021xPlan(root,profile,request,{'supplicant':'\n'.join(lines)+'\n','credentials':'\n'.join(credentials)+'\n','service':service})

class Ieee8021xManager:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise Ieee8021xError(f'No se sobreescriurà un enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name('.'+path.name+'.tmp'); tmp.write_text(content,encoding='utf-8'); tmp.chmod(mode); os.replace(tmp,path)
    def apply(self,plan:Ieee8021xPlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=tuple(plan.path(x) for x in ('supplicant','credentials','service')); state,snapshot,pending,renewal,diagnostics=(plan.path(x) for x in ('state','snapshot','pending','renewal','diagnostics'))
        if dry_run:return (*targets,state,pending,renewal,diagnostics)
        previous={str(p.relative_to(plan.rootfs)):p.read_text(encoding='utf-8') for p in targets if p.exists()}
        self._write(snapshot,json.dumps({'schema_version':1,'files':previous},indent=2,sort_keys=True)+'\n',0o600)
        self._write(pending,json.dumps({'schema_version':1,'status':'pending','eap':plan.request.eap},indent=2)+'\n',0o600)
        for name,path in zip(('supplicant','credentials','service'),targets): self._write(path,plan.files[name],0o600 if name=='credentials' else 0o640)
        self._write(state,json.dumps({'schema_version':1,'status':'applied','source':plan.request.source,'interface':plan.request.interface,'eap':plan.request.eap,'identity':plan.request.identity,'certificate_renewal_required':plan.request.eap=='tls'},indent=2,sort_keys=True)+'\n',0o640)
        self._write(renewal,json.dumps({'schema_version':1,'managed_by':'xaac-agent','action':'monitor-and-renew','certificate':plan.request.client_certificate},indent=2,sort_keys=True)+'\n',0o600)
        self._write(diagnostics,json.dumps({'schema_version':1,'checks':['wpa_cli status','systemctl status wpa_supplicant@<interface>'],'secrets_redacted':True},indent=2)+'\n',0o640)
        pending.unlink(missing_ok=True); return (*targets,state,snapshot,renewal,diagnostics)
    def rollback(self,plan:Ieee8021xPlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=tuple(plan.path(x) for x in ('supplicant','credentials','service')); snapshot,state=plan.path('snapshot'),plan.path('state')
        if not snapshot.exists(): raise Ieee8021xError('No hi ha snapshot IEEE 802.1X')
        data=json.loads(snapshot.read_text(encoding='utf-8')); files=data.get('files')
        if not isinstance(files,dict): raise Ieee8021xError('Snapshot IEEE 802.1X invàlid')
        if dry_run:return (*targets,state)
        for path in targets:
            key=str(path.relative_to(plan.rootfs))
            if key in files:self._write(path,files[key],0o600 if path==plan.path('credentials') else 0o640)
            else:path.unlink(missing_ok=True)
        self._write(state,json.dumps({'schema_version':1,'status':'rolled-back'},indent=2)+'\n',0o640); return (*targets,state)
