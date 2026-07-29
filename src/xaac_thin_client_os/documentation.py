"""Documentation bundle validation for phase 12.9."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class DocumentationError(RuntimeError):
    """Raised when the production documentation set is incomplete or unsafe."""

REQUIRED=("installation","administration","network","security","updates","recovery","development","troubleshooting")

def _relative(value: object, field: str) -> str:
    if not isinstance(value,str) or not value or value.startswith('/'):
        raise DocumentationError(f"Ruta relativa invàlida en {field}")
    if any(p in {'.','..'} for p in PurePosixPath(value).parts):
        raise DocumentationError(f"Ruta insegura en {field}")
    return value

def load_documentation_profile(path: Path) -> dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise DocumentationError(f"No s'ha pogut carregar la documentació: {exc}") from exc
    if not isinstance(raw,dict) or raw.get('schema_version')!=1 or raw.get('product')!='XAAC Thin Client OS':
        raise DocumentationError('Perfil de documentació invàlid')
    manuals=raw.get('manuals')
    if not isinstance(manuals,dict) or tuple(manuals)!=REQUIRED:
        raise DocumentationError('Conjunt de manuals incomplet o desordenat')
    raw['manuals']={k:_relative(v,f'manuals.{k}') for k,v in manuals.items()}
    outputs=raw.get('outputs')
    if not isinstance(outputs,dict) or set(outputs)!={'index','manifest'}: raise DocumentationError('outputs incomplets')
    raw['outputs']={k:_relative(v,f'outputs.{k}') for k,v in outputs.items()}
    return raw

@dataclass(frozen=True,slots=True)
class DocumentationPlan:
    root: Path
    profile: dict[str,Any]
    def output(self,key:str)->Path: return self.root/self.profile['outputs'][key]
    def manifest(self)->dict[str,object]:
        return {'schema_version':1,'product':'XAAC Thin Client OS','language':self.profile.get('language','ca'),'manuals':list(self.profile['manuals']),'manual_count':len(self.profile['manuals'])}

def create_documentation_plan(root:Path, profile_path:Path)->DocumentationPlan:
    resolved=root.resolve()
    if resolved==Path('/'): raise DocumentationError(f'Arrel de projecte insegura: {resolved}')
    profile=load_documentation_profile(profile_path)
    for name,rel in profile['manuals'].items():
        p=resolved/rel
        if p.is_symlink(): raise DocumentationError(f'Manual amb enllaç simbòlic: {name}')
        if not p.is_file(): raise DocumentationError(f'Manual absent: {name}')
        text=p.read_text(encoding='utf-8')
        if not text.startswith('# ') or len(text.split())<35: raise DocumentationError(f'Manual insuficient: {name}')
    return DocumentationPlan(resolved,profile)

class DocumentationBuilder:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise DocumentationError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def prepare(self,plan:DocumentationPlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=(plan.output('index'),plan.output('manifest'))
        if dry_run:return targets
        labels={'installation':'Instal·lació','administration':'Administració','network':'Xarxa','security':'Seguretat','updates':'Actualitzacions','recovery':'Recuperació','development':'Desenvolupament','troubleshooting':'Resolució de problemes'}
        lines=['# Documentació de XAAC Thin Client OS','','Manuals operatius i tècnics de la imatge de producció:','']
        for name,rel in plan.profile['manuals'].items(): lines.append(f"- [{labels[name]}]({Path(rel).name})")
        lines += ['','La configuració declarativa i el manifest permeten verificar que el conjunt és complet i reproduïble.','']
        self._write(plan.output('index'),'\n'.join(lines),0o644)
        self._write(plan.output('manifest'),json.dumps(plan.manifest(),ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o644)
        return targets
