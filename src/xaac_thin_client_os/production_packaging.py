"""Production packaging and APT publication plan for phase 12.10."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class ProductionPackagingError(RuntimeError):
    """Raised when packaging or publication configuration is unsafe."""

REQUIRED_CHANNELS=("laboratory","pilot","production")
REQUIRED_PACKAGES=("xaac-thin-client","xaac-agent","xaac-thin-client-os")

def _relative(value: object, field: str) -> str:
    if not isinstance(value,str) or not value or value.startswith('/'):
        raise ProductionPackagingError(f"Ruta relativa invàlida en {field}")
    if any(part in {'.','..'} for part in PurePosixPath(value).parts):
        raise ProductionPackagingError(f"Ruta insegura en {field}")
    return value

def load_production_packaging_profile(path: Path) -> dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise ProductionPackagingError(f"No s'ha pogut carregar el perfil: {exc}") from exc
    if not isinstance(raw,dict) or raw.get('schema_version')!=1 or raw.get('product')!='XAAC Thin Client OS':
        raise ProductionPackagingError('Perfil de packaging invàlid')
    packages=raw.get('packages')
    if not isinstance(packages,dict) or tuple(packages)!=REQUIRED_PACKAGES:
        raise ProductionPackagingError('Conjunt de paquets incomplet o desordenat')
    for name,data in packages.items():
        if not isinstance(data,dict) or not isinstance(data.get('architecture'),str): raise ProductionPackagingError(f'Paquet invàlid: {name}')
        data['source']=_relative(data.get('source'),f'packages.{name}.source')
    channels=raw.get('channels')
    if not isinstance(channels,dict) or tuple(channels)!=REQUIRED_CHANNELS: raise ProductionPackagingError('Canals incomplets o desordenats')
    if any(not isinstance(v,str) or not v for v in channels.values()): raise ProductionPackagingError('Distribució de canal invàlida')
    signing=raw.get('signing')
    if not isinstance(signing,dict) or signing.get('required') is not True or signing.get('digest')!='SHA256': raise ProductionPackagingError('Política de signatura invàlida')
    outputs=raw.get('outputs')
    if not isinstance(outputs,dict) or set(outputs)!={'manifest','script','repository'}: raise ProductionPackagingError('outputs incomplets')
    raw['outputs']={k:_relative(v,f'outputs.{k}') for k,v in outputs.items()}
    return raw

@dataclass(frozen=True,slots=True)
class ProductionPackagingPlan:
    root: Path
    profile: dict[str,Any]
    def output(self,key:str)->Path:return self.root/self.profile['outputs'][key]
    def manifest(self)->dict[str,object]:
        return {'schema_version':1,'product':'XAAC Thin Client OS','version':self.profile['version'],'architecture':self.profile['architecture'],'packages':list(self.profile['packages']),'metapackage':'xaac-thin-client-os','channels':list(self.profile['channels']),'signed':True,'digest':'SHA256'}

def create_production_packaging_plan(root:Path, profile_path:Path)->ProductionPackagingPlan:
    resolved=root.resolve()
    if resolved==Path('/'): raise ProductionPackagingError(f'Arrel insegura: {resolved}')
    profile=load_production_packaging_profile(profile_path)
    for name,data in profile['packages'].items():
        source=resolved/data['source']
        if source.is_symlink(): raise ProductionPackagingError(f'Font amb enllaç simbòlic: {name}')
        if not source.exists(): raise ProductionPackagingError(f'Font absent: {name}')
    return ProductionPackagingPlan(resolved,profile)

class ProductionPackagingBuilder:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise ProductionPackagingError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def prepare(self,plan:ProductionPackagingPlan,*,dry_run:bool=False)->tuple[Path,...]:
        targets=(plan.output('manifest'),plan.output('script'),plan.output('repository'))
        if dry_run:return targets
        manifest=json.dumps(plan.manifest(),ensure_ascii=False,indent=2,sort_keys=True)+'\n'
        script='''#!/bin/sh\nset -eu\ncommand -v dpkg-buildpackage >/dev/null\ncommand -v reprepro >/dev/null\ncommand -v gpg >/dev/null\n: "${XAAC_SIGNING_KEY:?XAAC_SIGNING_KEY is required}"\nfor channel in laboratory pilot production; do\n  reprepro -b "$REPOSITORY" includedeb "$channel" "$@"\ndone\nreprepro -b "$REPOSITORY" export\nfind "$REPOSITORY/dists" -name Release -exec gpg --batch --yes --local-user "$XAAC_SIGNING_KEY" --armor --detach-sign -o '{}.gpg' '{}' \\;\n'''
        repo='''Codename: laboratory\nComponents: main\nArchitectures: amd64 all\nSignWith: yes\n\nCodename: pilot\nComponents: main\nArchitectures: amd64 all\nSignWith: yes\n\nCodename: production\nComponents: main\nArchitectures: amd64 all\nSignWith: yes\n'''
        self._write(targets[0],manifest,0o644); self._write(targets[1],script,0o750); self._write(targets[2],repo,0o644)
        return targets
