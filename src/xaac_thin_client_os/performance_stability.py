"""Deterministic performance and stability validation assets for phase 12.8."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class PerformanceStabilityError(RuntimeError):
    """Raised when performance policy is incomplete or unsafe."""

def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith('/'):
        raise PerformanceStabilityError(f"Ruta relativa invàlida en {field}")
    if any(part in {'.','..'} for part in PurePosixPath(value).parts):
        raise PerformanceStabilityError(f"Ruta insegura en {field}")
    return value

def load_performance_stability(path: Path) -> dict[str, Any]:
    try:
        raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc:
        raise PerformanceStabilityError(f"No s'ha pogut carregar la política de rendiment: {exc}") from exc
    if not isinstance(raw,dict) or raw.get('schema_version')!=1:
        raise PerformanceStabilityError('Política de rendiment invàlida')
    if raw.get('product')!='XAAC Thin Client OS' or raw.get('hardware_profile')!='wyse3040':
        raise PerformanceStabilityError('Producte o perfil no suportats')
    metrics=raw.get('metrics'); required=['boot_time','memory','cpu','disk','temperature','long_session','intermittent_network']
    if not isinstance(metrics,dict) or list(metrics)!=required:
        raise PerformanceStabilityError('Mètriques incompletes o desordenades')
    for name in required:
        item=metrics[name]
        if not isinstance(item,dict) or item.get('enabled') is not True:
            raise PerformanceStabilityError(f'Mètrica obligatòria invàlida: {name}')
        command=item.get('command'); threshold=item.get('threshold')
        if not isinstance(command,str) or not command:
            raise PerformanceStabilityError(f'Ordre invàlida: {name}')
        if not isinstance(threshold,(int,float)) or threshold<=0:
            raise PerformanceStabilityError(f'Llindar invàlid: {name}')
    execution=raw.get('execution')
    if not isinstance(execution,dict) or execution.get('fail_fast') is not False:
        raise PerformanceStabilityError("La suite ha d'executar totes les mètriques")
    if not isinstance(execution.get('sample_interval_seconds'),int) or execution['sample_interval_seconds']<1:
        raise PerformanceStabilityError('Interval de mostreig invàlid')
    if not isinstance(execution.get('long_session_hours'),int) or not 1<=execution['long_session_hours']<=168:
        raise PerformanceStabilityError('Duració de sessió invàlida')
    outputs=raw.get('outputs'); expected={'manifest','runner','report_schema','guide'}
    if not isinstance(outputs,dict) or set(outputs)!=expected:
        raise PerformanceStabilityError('outputs incomplets')
    raw['outputs']={k:_safe_relative(v,f'outputs.{k}') for k,v in outputs.items()}
    return raw

@dataclass(frozen=True,slots=True)
class PerformanceStabilityPlan:
    project_root: Path
    profile: dict[str,Any]
    def output(self,key:str)->Path: return self.project_root/self.profile['outputs'][key]
    def manifest(self)->dict[str,object]:
        return {'schema_version':1,'profile_id':self.profile['profile_id'],'product':'XAAC Thin Client OS','hardware_profile':'wyse3040','metrics':list(self.profile['metrics']),'metric_count':len(self.profile['metrics']),'long_session_hours':self.profile['execution']['long_session_hours'],'fail_fast':False}

def create_performance_stability_plan(project_root:Path,profile_path:Path)->PerformanceStabilityPlan:
    root=project_root.resolve()
    if root==Path('/'):
        raise PerformanceStabilityError(f'Arrel de projecte insegura: {root}')
    return PerformanceStabilityPlan(root,load_performance_stability(profile_path))

class PerformanceStabilityBuilder:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise PerformanceStabilityError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f: f.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def prepare(self,plan:PerformanceStabilityPlan,*,dry_run:bool=False)->tuple[Path,...]:
        keys=('manifest','runner','report_schema','guide'); targets=tuple(plan.output(k) for k in keys)
        if dry_run:return targets
        self._write(plan.output('manifest'),json.dumps(plan.manifest(),ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o644)
        lines=['#!/bin/sh','set -u','REPORT=${1:-/var/log/xaac/performance-stability.json}','TMP=$(mktemp)',"trap 'rm -f \"$TMP\"' EXIT",'failed=0',"printf '%s\\n' '[' > \"$TMP\"",'first=1']
        for name,spec in plan.profile['metrics'].items():
            cmd=spec['command'].replace('\\','\\\\').replace('"','\\"'); threshold=spec['threshold']; comparator=spec.get('comparator','max')
            testop='-le' if comparator=='max' else '-ge'
            lines += [f'value=$(sh -c "{cmd}" 2>/dev/null || printf invalid)',f'if [ "$value" != invalid ] && awk "BEGIN {{exit !($value {"<=" if comparator=="max" else ">="} {threshold})}}"; then status=passed; else status=failed; failed=$((failed+1)); fi','[ "$first" -eq 1 ] || printf ",\\n" >> "$TMP"','first=0',f'printf \'  {{"metric":"{name}","value":"%s","threshold":{threshold},"comparator":"{comparator}","status":"%s"}}\' "$value" "$status" >> "$TMP"']
        lines += ["printf '\\n]\\n' >> \"$TMP\"",'install -d -m 0750 "$(dirname "$REPORT")"','install -m 0640 "$TMP" "$REPORT"','[ "$failed" -eq 0 ]']
        self._write(plan.output('runner'),'\n'.join(lines)+'\n',0o750)
        schema={'$schema':'https://json-schema.org/draft/2020-12/schema','type':'array','items':{'type':'object','required':['metric','value','threshold','comparator','status'],'properties':{'metric':{'enum':list(plan.profile['metrics'])},'value':{'type':'string'},'threshold':{'type':'number'},'comparator':{'enum':['max','min']},'status':{'enum':['passed','failed']}},'additionalProperties':False}}
        self._write(plan.output('report_schema'),json.dumps(schema,indent=2,sort_keys=True)+'\n',0o644)
        guide=['# Validació de rendiment i estabilitat','',f"Duració mínima de sessió prolongada: {plan.profile['execution']['long_session_hours']} hores.",'','Executeu el runner en un Dell Wyse 3040 amb la imatge de producció i conserveu informe i evidències.','']+[f"- **{n}**: llindar {s['comparator']} {s['threshold']} {s['unit']}" for n,s in plan.profile['metrics'].items()]
        self._write(plan.output('guide'),'\n'.join(guide)+'\n',0o644)
        return targets
