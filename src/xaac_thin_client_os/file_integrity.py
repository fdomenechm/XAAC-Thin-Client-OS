"""File integrity policy, verification and repair (phase 9.6)."""
from __future__ import annotations
import fnmatch, hashlib, json, os, shutil, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class FileIntegrityError(RuntimeError): pass

def _safe(v: object, field: str) -> str:
    if not isinstance(v, str) or not v.startswith('/') or '..' in PurePosixPath(v).parts:
        raise FileIntegrityError(f"Ruta insegura en {field}")
    return v

def load_file_integrity_policy(path: Path) -> dict[str, Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as e: raise FileIntegrityError(f"No s'ha pogut carregar la política: {e}") from e
    if not isinstance(raw,dict) or raw.get('schema_version')!=1 or raw.get('algorithm')!='sha256':
        raise FileIntegrityError('Política d’integritat invàlida')
    paths=raw.get('monitored_paths')
    if not isinstance(paths,list) or not paths: raise FileIntegrityError('monitored_paths ha de ser una llista no buida')
    raw['monitored_paths']=[_safe(x,'monitored_paths') for x in paths]
    if len(raw['monitored_paths'])!=len(set(raw['monitored_paths'])): raise FileIntegrityError('Rutes monitorades duplicades')
    ex=raw.get('exclude_patterns',[])
    if not isinstance(ex,list) or not all(isinstance(x,str) and x and '/' not in x for x in ex): raise FileIntegrityError('Patrons d’exclusió invàlids')
    for section,key in (('alert','state'),('alert','log'),('repair','baseline_dir')):
        if not isinstance(raw.get(section),dict): raise FileIntegrityError(f'{section} és obligatori')
        raw[section][key]=_safe(raw[section].get(key),f'{section}.{key}')
    out=raw.get('outputs')
    required={'manifest','policy','verifier','service','timer'}
    if not isinstance(out,dict) or set(out)!=required: raise FileIntegrityError('outputs incomplet')
    raw['outputs']={k:_safe(v,f'outputs.{k}') for k,v in out.items()}
    return raw

@dataclass(frozen=True, slots=True)
class FileIntegrityPlan:
    rootfs: Path; profile: dict[str,Any]
    def destination(self, path: str)->Path: return self.rootfs/path.lstrip('/')
    def output(self,key:str)->Path:return self.destination(self.profile['outputs'][key])
    def manifest(self)->dict[str,object]: return {'schema_version':1,'policy_id':self.profile['policy_id'],'algorithm':'sha256','monitored_path_count':len(self.profile['monitored_paths']),'repair_enabled':bool(self.profile['repair'].get('enabled'))}

def create_file_integrity_plan(rootfs:Path,profile_path:Path)->FileIntegrityPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise FileIntegrityError(f'Rootfs insegur: {root}')
    return FileIntegrityPlan(root,load_file_integrity_policy(profile_path))

class FileIntegrityManager:
    @staticmethod
    def _write(path:Path, content:str, mode:int)->None:
        if path.is_symlink(): raise FileIntegrityError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    @staticmethod
    def _hash(path:Path)->str:
        h=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        return h.hexdigest()
    def _files(self,plan:FileIntegrityPlan):
        generated = {plan.output(k) for k in plan.profile['outputs']}
        generated.add(plan.destination(plan.profile['alert']['state']))
        baseline_root = plan.destination(plan.profile['repair']['baseline_dir'])
        for logical in sorted(plan.profile['monitored_paths']):
            base=plan.destination(logical)
            if base.is_symlink(): raise FileIntegrityError(f'Ruta monitorada amb enllaç simbòlic: {base}')
            if base.is_file(): candidates=[base]
            elif base.is_dir(): candidates=sorted(p for p in base.rglob('*') if p.is_file() and not p.is_symlink())
            else: continue
            for p in candidates:
                if p in generated or p == baseline_root or baseline_root in p.parents: continue
                if any(fnmatch.fnmatch(p.name,pat) for pat in plan.profile['exclude_patterns']): continue
                yield p
    def install(self,plan:FileIntegrityPlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=(plan.output('manifest'),plan.output('policy'),plan.output('verifier'),plan.output('service'),plan.output('timer'),plan.destination(plan.profile['alert']['state']))
        if dry_run:return targets
        entries=[]; baseline=plan.destination(plan.profile['repair']['baseline_dir'])
        for p in self._files(plan):
            rel='/' + p.relative_to(plan.rootfs).as_posix(); entries.append({'path':rel,'sha256':self._hash(p),'size':p.stat().st_size})
            dst=baseline/rel.lstrip('/'); dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dst)
        manifest={'schema_version':1,'algorithm':'sha256','policy_id':plan.profile['policy_id'],'files':entries}
        policy={k:v for k,v in plan.profile.items() if k!='outputs'}
        script='''#!/usr/bin/env python3\nimport hashlib,json,pathlib,shutil,sys\nroot=pathlib.Path('/')\nm=json.loads(pathlib.Path('/var/lib/xaac-integrity/manifest.json').read_text())\nb=pathlib.Path('/var/lib/xaac-integrity/baseline'); repair='--repair' in sys.argv; changed=[]\nfor e in m['files']:\n p=root/e['path'].lstrip('/'); ok=p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==e['sha256']\n if not ok:\n  changed.append(e['path'])\n  if repair:\n   p.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(b/e['path'].lstrip('/'),p)\nstate={'schema_version':1,'status':'ok' if not changed else ('repaired' if repair else 'alert'),'changed':changed}\npathlib.Path('/var/lib/xaac-agent/security').mkdir(parents=True,exist_ok=True)\npathlib.Path('/var/lib/xaac-agent/security/file-integrity.json').write_text(json.dumps(state,indent=2)+'\\n')\nraise SystemExit(0 if not changed or repair else 3)\n'''
        service='''[Unit]\nDescription=XAAC file integrity verification\nAfter=local-fs.target\n[Service]\nType=oneshot\nExecStart=/usr/local/libexec/xaac/verify-file-integrity\nNoNewPrivileges=yes\nProtectSystem=strict\nProtectHome=yes\nReadWritePaths=/var/lib/xaac-agent/security /var/log/xaac\n'''
        timer='''[Unit]\nDescription=Periodic XAAC file integrity verification\n[Timer]\nOnBootSec=5min\nOnUnitActiveSec=1h\nPersistent=true\n[Install]\nWantedBy=timers.target\n'''
        self._write(plan.output('manifest'),json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640)
        self._write(plan.output('policy'),json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640)
        self._write(plan.output('verifier'),script,0o750); self._write(plan.output('service'),service,0o644); self._write(plan.output('timer'),timer,0o644)
        state={'schema_version':1,'status':'baseline-created','file_count':len(entries),'algorithm':'sha256'}
        self._write(plan.destination(plan.profile['alert']['state']),json.dumps(state,indent=2,sort_keys=True)+'\n',0o640)
        return targets
    def verify(self,plan:FileIntegrityPlan,*,repair:bool=False)->dict[str,object]:
        try:m=json.loads(plan.output('manifest').read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError) as e:raise FileIntegrityError(f'Manifest no disponible: {e}') from e
        changed=[]; repaired=[]; baseline=plan.destination(plan.profile['repair']['baseline_dir'])
        for e in m.get('files',[]):
            p=plan.destination(e['path']); ok=p.is_file() and self._hash(p)==e['sha256']
            if not ok:
                changed.append(e['path'])
                if repair:
                    src=baseline/e['path'].lstrip('/')
                    if not src.is_file(): raise FileIntegrityError(f'Baseline absent: {e["path"]}')
                    p.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,p); repaired.append(e['path'])
        return {'status':'ok' if not changed else ('repaired' if repair else 'alert'),'changed':changed,'repaired':repaired}
