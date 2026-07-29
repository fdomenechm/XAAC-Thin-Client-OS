"""Secure Boot and TPM feasibility policy (phase 9.8)."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class SecureBootTpmError(RuntimeError): pass

def _path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith('/') or '..' in PurePosixPath(value).parts:
        raise SecureBootTpmError(f"Ruta insegura en {field}")
    return value

def load_secure_boot_tpm_policy(path: Path) -> dict[str, Any]:
    try: raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc: raise SecureBootTpmError(f"No s'ha pogut carregar la política: {exc}") from exc
    if not isinstance(raw, dict) or raw.get('schema_version') != 1: raise SecureBootTpmError('Política Secure Boot/TPM invàlida')
    if raw.get('hardware_profile') != 'wyse3040': raise SecureBootTpmError('Perfil de maquinari no suportat')
    sb, tpm, risks, outputs = raw.get('secure_boot'), raw.get('tpm'), raw.get('accepted_risks'), raw.get('outputs')
    if not isinstance(sb, dict) or sb.get('feasibility') not in {'yes','conditional','no'}: raise SecureBootTpmError('Viabilitat de Secure Boot invàlida')
    if sb.get('implementation') != 'shim-grub-signed' or sb.get('key_management') != 'distribution-managed': raise SecureBootTpmError('Implementació Secure Boot no suportada')
    if sb.get('require_signed_kernel') is not True or sb.get('require_signed_bootloader') is not True: raise SecureBootTpmError('Secure Boot no pot permetre artefactes sense signar')
    if sb.get('allow_custom_keys') is not False: raise SecureBootTpmError('Les claus personalitzades no estan autoritzades en aquesta fase')
    checks = sb.get('checks')
    if not isinstance(checks, list) or len(checks) != len(set(checks)) or not all(isinstance(x,str) and x for x in checks): raise SecureBootTpmError('Comprovacions Secure Boot invàlides')
    if not isinstance(tpm, dict) or tpm.get('feasibility') not in {'yes','optional','no'} or tpm.get('minimum_version') != '2.0': raise SecureBootTpmError('Política TPM invàlida')
    if tpm.get('required_for_boot') is not False: raise SecureBootTpmError('TPM no pot ser obligatori per arrancar')
    if not isinstance(risks, list) or not risks: raise SecureBootTpmError('Cal documentar riscos acceptats')
    ids=[]
    for item in risks:
        if not isinstance(item,dict) or not all(isinstance(item.get(k),str) and item[k] for k in ('id','statement','treatment')): raise SecureBootTpmError('Risc acceptat invàlid')
        ids.append(item['id'])
    if len(ids)!=len(set(ids)): raise SecureBootTpmError('Identificadors de risc duplicats')
    required={'policy','probe','state','adr'}
    if not isinstance(outputs,dict) or set(outputs)!=required: raise SecureBootTpmError('outputs incomplet')
    raw['outputs']={k:_path(v,f'outputs.{k}') for k,v in outputs.items()}
    return raw

@dataclass(frozen=True, slots=True)
class SecureBootTpmPlan:
    rootfs: Path
    profile: dict[str, Any]
    def output(self, key: str) -> Path: return self.rootfs / self.profile['outputs'][key].lstrip('/')
    def manifest(self) -> dict[str, object]:
        return {'schema_version':1,'policy_id':self.profile['policy_id'],'hardware_profile':self.profile['hardware_profile'],'secure_boot_feasibility':self.profile['secure_boot']['feasibility'],'tpm_feasibility':self.profile['tpm']['feasibility'],'accepted_risk_count':len(self.profile['accepted_risks'])}

def create_secure_boot_tpm_plan(rootfs: Path, profile_path: Path) -> SecureBootTpmPlan:
    root=rootfs.resolve()
    if root==Path('/') or root.name!='rootfs': raise SecureBootTpmError(f'Rootfs insegur: {root}')
    return SecureBootTpmPlan(root, load_secure_boot_tpm_policy(profile_path))

class SecureBootTpmInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink(): raise SecureBootTpmError(f'Destinació amb enllaç simbòlic: {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as handle: handle.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def install(self, plan: SecureBootTpmPlan, *, dry_run: bool=False) -> tuple[Path,...]:
        targets=tuple(plan.output(k) for k in ('policy','probe','state','adr'))
        if dry_run:return targets
        profile=plan.profile
        probe='''#!/bin/sh\nset -eu\nsecure_boot=unavailable\n[ -d /sys/firmware/efi ] && secure_boot=disabled\nfor f in /sys/firmware/efi/efivars/SecureBoot-*; do\n  [ -r "$f" ] || continue\n  value=$(od -An -t u1 -j 4 -N 1 "$f" | tr -d ' ')\n  [ "$value" = 1 ] && secure_boot=enabled || secure_boot=disabled\ndone\ntpm=absent\n[ -c /dev/tpmrm0 ] || [ -c /dev/tpm0 ] && tpm=present\nprintf '{"schema_version":1,"secure_boot":"%s","tpm":"%s"}\\n' "$secure_boot" "$tpm"\n'''
        adr='''# ADR-0009 — Secure Boot i TPM al Dell Wyse 3040\n\n## Estat\nAcceptat.\n\n## Decisió\nLa imatge mantindrà una cadena d’arrencada signada basada en `shim-signed`, `grub-efi-amd64-signed` i kernel Debian signat. L’activació de Secure Boot serà condicional a la capacitat real del firmware. TPM 2.0 serà opcional i no serà requisit d’arrencada, recuperació ni administració local.\n\n## Conseqüències\nEs pot aprofitar Secure Boot i TPM quan el maquinari els expose, però el mateix artefacte continua sent instal·lable i recuperable en variants sense TPM o sense controls Secure Boot utilitzables. No s’inclouen claus privades ni s’implanta una PKI pròpia en aquesta fase.\n'''
        state={'status':'configured','decision':'conditional-secure-boot-optional-tpm',**plan.manifest()}
        policy={k:v for k,v in profile.items() if k!='outputs'}
        self._write(plan.output('policy'),json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o644)
        self._write(plan.output('probe'),probe,0o750)
        self._write(plan.output('state'),json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+'\n',0o640)
        self._write(plan.output('adr'),adr,0o644)
        return targets
