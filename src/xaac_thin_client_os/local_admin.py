"""Local administrator profile for XAAC Thin Client OS (phase 7.6)."""
from __future__ import annotations
import json, os, re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class LocalAdminError(RuntimeError): pass

def _abs(value:str, field:str)->PurePosixPath:
    p=PurePosixPath(value)
    if not p.is_absolute() or '..' in p.parts: raise LocalAdminError(f'Ruta invàlida: {field}')
    return p

def load_local_admin_profile(path:Path)->dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise LocalAdminError(f'No es pot carregar el perfil administrador: {exc}') from exc
    if not isinstance(raw,dict) or raw.get('schema_version')!=1: raise LocalAdminError('Perfil administrador invàlid')
    if raw.get('backend')!='systemd-sysusers': raise LocalAdminError('Backend administrador no suportat')
    expected={'sysusers','tmpfiles','sudoers','menu','profile','first_login','audit_rules','state','pending','snapshot'}
    if not isinstance(raw.get('paths'),dict) or set(raw['paths'])!=expected: raise LocalAdminError('Rutes administrador incompletes')
    for k,v in raw['paths'].items(): _abs(v,f'paths.{k}')
    return raw

@dataclass(frozen=True,slots=True)
class LocalAdminRequest:
    source:str='local'; username:str='xaac-admin'; password_hash:str|None=None; force_password_change:bool=True

@dataclass(frozen=True,slots=True)
class LocalAdminPlan:
    rootfs:Path; profile:dict[str,Any]; request:LocalAdminRequest; files:dict[str,str]
    def path(self,name:str)->Path: return self.rootfs/_abs(self.profile['paths'][name],name).relative_to('/')

def _safe_username(value:str)->str:
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}',value): raise LocalAdminError('Nom administrador invàlid')
    return value

def _safe_hash(value:str|None)->str:
    if value is None: return '!'
    if '\n' in value or '\r' in value or ':' in value or not value.startswith(('$6$','$y$')): raise LocalAdminError('Hash de contrasenya invàlid')
    return value

def create_local_admin_plan(rootfs:Path,profile_path:Path,request:LocalAdminRequest)->LocalAdminPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise LocalAdminError(f'Rootfs insegur: {root}')
    profile=load_local_admin_profile(profile_path); account=profile['account']; policy=profile['policy']
    if request.source not in policy['allowed_sources']: raise LocalAdminError('Font no autoritzada')
    username=_safe_username(request.username)
    if username!=account['username']: raise LocalAdminError('Usuari administrador fora de política')
    pwd=_safe_hash(request.password_hash)
    group_lines=''.join(f'm {username} {group}\n' for group in account['groups'])
    sysusers=f'# Managed by XAAC Thin Client OS\nu {username} - "XAAC local administrator" {account["home"]} {account["shell"]}\n'+group_lines
    tmpfiles=f'd {account["home"]} 0750 {username} {username} -\nd /var/lib/xaac/admin 0750 root {username} -\n'
    sudoers=(f'Defaults:{username} use_pty,log_output,passwd_timeout=1\n'
             f'{username} ALL=(root) /usr/local/sbin/xaac-admin-menu, /usr/bin/systemctl status *, /usr/bin/journalctl *\n')
    menu='''#!/bin/sh
set -eu
printf '%s\n' 'XAAC Thin Client OS — Administració local' '1) Estat de xarxa' '2) Estat de serveis XAAC' '3) Registres del sistema' '4) Canviar contrasenya' '0) Eixir'
read -r choice
case "$choice" in
  1) networkctl status --no-pager ;;
  2) systemctl status xaac-agent.service xaac-thin-client.service --no-pager ;;
  3) journalctl -b -p warning --no-pager -n 200 ;;
  4) passwd ;;
  0) exit 0 ;;
  *) echo 'Opció invàlida' >&2; exit 2 ;;
esac
'''
    first=f'''#!/bin/sh
set -eu
marker=/var/lib/xaac/admin/password-changed
[ -e "$marker" ] && exit 0
passwd {username}
install -o root -g {username} -m 0640 /dev/null "$marker"
logger -t xaac-admin 'mandatory password change completed'
'''
    profile_sh=f'''# Managed by XAAC Thin Client OS
if [ "$(id -un 2>/dev/null)" = "{username}" ] && [ -t 0 ]; then
  /usr/local/libexec/xaac-admin-first-login
  exec sudo /usr/local/sbin/xaac-admin-menu
fi
'''
    audit=f'-w /etc/sudoers.d/xaac-admin -p wa -k xaac-admin-config\n-w /var/lib/xaac/admin -p wa -k xaac-admin-state\n-a always,exit -F arch=b64 -S execve -F euid=0 -F auid>=1000 -F auid!=4294967295 -k xaac-admin-command\n'
    return LocalAdminPlan(root,profile,request,{'sysusers':sysusers,'tmpfiles':tmpfiles,'sudoers':sudoers,'menu':menu,'profile':profile_sh,'first_login':first,'audit_rules':audit,'password_hash':pwd})

class LocalAdminManager:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise LocalAdminError(f'No se sobreescriurà un enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name('.'+path.name+'.tmp'); tmp.write_text(content,encoding='utf-8'); tmp.chmod(mode); os.replace(tmp,path)
    def apply(self,plan:LocalAdminPlan,*,dry_run:bool=False)->tuple[Path,...]:
        names=('sysusers','tmpfiles','sudoers','menu','profile','first_login','audit_rules'); targets=tuple(plan.path(n) for n in names)
        state,pending,snapshot=plan.path('state'),plan.path('pending'),plan.path('snapshot')
        shadow=plan.rootfs/'etc/shadow'
        if dry_run:return (*targets,state,pending)
        previous={str(p.relative_to(plan.rootfs)):p.read_text(encoding='utf-8') for p in targets if p.exists()}
        self._write(snapshot,json.dumps({'schema_version':1,'files':previous},indent=2,sort_keys=True)+'\n',0o600)
        self._write(pending,json.dumps({'schema_version':1,'status':'pending'},indent=2)+'\n',0o600)
        modes={'sudoers':0o440,'menu':0o750,'first_login':0o750,'audit_rules':0o640}
        for n,p in zip(names,targets): self._write(p,plan.files[n],modes.get(n,0o644))
        if shadow.exists():
            lines=shadow.read_text(encoding='utf-8').splitlines(); found=False; out=[]
            for line in lines:
                if line.startswith(plan.request.username+':'):
                    parts=line.split(':'); parts[1]=plan.files['password_hash']; parts[2]='0' if plan.request.force_password_change else parts[2]; line=':'.join(parts); found=True
                out.append(line)
            if found:self._write(shadow,'\n'.join(out)+'\n',0o640)
        self._write(state,json.dumps({'schema_version':1,'status':'applied','source':plan.request.source,'username':plan.request.username,'password_change_required':plan.request.force_password_change,'sudo_policy':'restricted','audit_enabled':True},indent=2,sort_keys=True)+'\n',0o640)
        pending.unlink(missing_ok=True); return (*targets,state,snapshot)
    def rollback(self,plan:LocalAdminPlan,*,dry_run:bool=False)->tuple[Path,...]:
        names=('sysusers','tmpfiles','sudoers','menu','profile','first_login','audit_rules'); targets=tuple(plan.path(n) for n in names); snapshot,state=plan.path('snapshot'),plan.path('state')
        if not snapshot.exists(): raise LocalAdminError('No hi ha snapshot administrador')
        data=json.loads(snapshot.read_text(encoding='utf-8')); files=data.get('files')
        if not isinstance(files,dict): raise LocalAdminError('Snapshot administrador invàlid')
        if dry_run:return (*targets,state)
        for p in targets:
            key=str(p.relative_to(plan.rootfs))
            if key in files:self._write(p,files[key],0o440 if p==plan.path('sudoers') else (0o750 if p in (plan.path('menu'),plan.path('first_login')) else 0o644))
            else:p.unlink(missing_ok=True)
        self._write(state,json.dumps({'schema_version':1,'status':'rolled-back'},indent=2)+'\n',0o640); return (*targets,state)
