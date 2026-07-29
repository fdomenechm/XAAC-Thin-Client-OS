"""Safe, auditable factory reset configuration for phase 11.6."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class FactoryResetError(RuntimeError):
    """Raised when the factory reset policy is incomplete or unsafe."""

_REQUIRED_OUTPUTS={"policy","state","service","first_boot_service","runner","first_boot_runner"}

def _path(value: object, field: str) -> str:
    if not isinstance(value,str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise FactoryResetError(f"Ruta insegura en {field}")
    return value

def load_factory_reset(path: Path) -> dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError,yaml.YAMLError) as exc: raise FactoryResetError(f"No s'ha pogut carregar la política de factory reset: {exc}") from exc
    if not isinstance(raw,dict) or raw.get("schema_version")!=1: raise FactoryResetError("Política de factory reset invàlida")
    if raw.get("hardware_profile")!="wyse3040": raise FactoryResetError("Perfil de maquinari no suportat")
    confirmation=raw.get("confirmation")
    if not isinstance(confirmation,dict) or confirmation.get("require_local_admin") is not True or confirmation.get("require_physical_presence") is not True or confirmation.get("require_exact_phrase")!="RESET XAAC DEVICE":
        raise FactoryResetError("Confirmació de factory reset insuficient")
    timeout=confirmation.get("timeout_seconds")
    if not isinstance(timeout,int) or isinstance(timeout,bool) or not 30<=timeout<=300: raise FactoryResetError("Temps de confirmació invàlid")
    preserve=raw.get("preserve")
    if not isinstance(preserve,dict) or any(preserve.get(k) is not True for k in ("device_identity","enrollment","recovery_audit","network_bootstrap")):
        raise FactoryResetError("Dades preservades incompletes")
    remove=raw.get("remove")
    if not isinstance(remove,dict) or any(remove.get(k) is not True for k in ("kiosk_state","application_cache","downloaded_updates","temporary_credentials","user_data")):
        raise FactoryResetError("Dades a eliminar incompletes")
    restore=raw.get("restore")
    if not isinstance(restore,dict) or restore.get("source")!="recovery_partition" or restore.get("require_signature") is not True or restore.get("hash_algorithm")!="sha256" or restore.get("transactional") is not True or restore.get("verify_before_switch") is not True:
        raise FactoryResetError("Restauració no verificable o no transaccional")
    first=raw.get("first_boot")
    if not isinstance(first,dict) or any(first.get(k) is not True for k in ("enable_service","regenerate_machine_id","reapply_preserved_identity","validate_hardware","reconcile_enrollment","notify_agent")):
        raise FactoryResetError("Primer inici incomplet")
    audit=raw.get("audit")
    if not isinstance(audit,dict) or any(audit.get(k) is not True for k in ("enabled","persistent","include_operator","include_reason","include_manifest_hash")):
        raise FactoryResetError("Auditoria insuficient")
    safety=raw.get("safety")
    if not isinstance(safety,dict) or safety.get("automatic_reset") is not False or safety.get("remote_unattended_reset") is not False or safety.get("fail_closed") is not True or safety.get("require_ac_power") is not True:
        raise FactoryResetError("Política de seguretat del factory reset invàlida")
    outputs=raw.get("outputs")
    if not isinstance(outputs,dict) or set(outputs)!=_REQUIRED_OUTPUTS: raise FactoryResetError("outputs incomplet")
    raw["outputs"]={k:_path(v,f"outputs.{k}") for k,v in outputs.items()}
    return raw

@dataclass(frozen=True,slots=True)
class FactoryResetPlan:
    rootfs: Path
    profile: dict[str,Any]
    def output(self,key:str)->Path: return self.rootfs/self.profile["outputs"][key].lstrip("/")
    def manifest(self)->dict[str,object]:
        return {"schema_version":1,"reset_id":self.profile["reset_id"],"preserved_items":len(self.profile["preserve"]),"removed_items":len(self.profile["remove"]),"restore_source":"recovery_partition","automatic_reset":False}

def create_factory_reset_plan(rootfs:Path,profile_path:Path)->FactoryResetPlan:
    root=rootfs.resolve()
    if root==Path("/") or root.name!="rootfs": raise FactoryResetError(f"Rootfs insegur: {root}")
    return FactoryResetPlan(root,load_factory_reset(profile_path))

class FactoryResetInstaller:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise FactoryResetError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream: stream.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def install(self,plan:FactoryResetPlan,*,dry_run:bool=False)->tuple[Path,...]:
        order=("policy","state","service","first_boot_service","runner","first_boot_runner"); targets=tuple(plan.output(k) for k in order)
        if dry_run:return targets
        policy={k:v for k,v in plan.profile.items() if k!="outputs"}
        state={**plan.manifest(),"status":"idle","requested_at":None,"completed_at":None,"operator":None,"reason":None,"last_error":None}
        service="""[Unit]\nDescription=XAAC controlled factory reset\nRequires=recovery.mount\nAfter=recovery.mount\nConditionACPower=true\n\n[Service]\nType=oneshot\nExecStart=/usr/libexec/xaac-factory-reset\nUser=root\nGroup=root\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=read-only\nProtectSystem=strict\nReadWritePaths=/var/lib/xaac-recovery /var/lib/xaac /etc/xaac\nLockPersonality=yes\nRestrictRealtime=yes\nUMask=0027\n"""
        first_service="""[Unit]\nDescription=XAAC first boot after factory reset\nAfter=local-fs.target network-online.target\nWants=network-online.target\nConditionPathExists=/var/lib/xaac-recovery/factory-reset.pending\n\n[Service]\nType=oneshot\nExecStart=/usr/libexec/xaac-factory-reset-first-boot\nUser=root\nGroup=root\nNoNewPrivileges=yes\nProtectSystem=strict\nReadWritePaths=/etc/machine-id /var/lib/dbus /var/lib/xaac /var/lib/xaac-recovery\nUMask=0027\n\n[Install]\nWantedBy=multi-user.target\n"""
        runner="""#!/bin/sh\nset -eu\nPOLICY=/etc/xaac/recovery/factory-reset.json\nSTATE=/var/lib/xaac-recovery/factory-reset-state.json\n[ -r \"$POLICY\" ] || exit 2\n[ -r /recovery/recovery-rootfs.squashfs ] || exit 3\n[ -r /recovery/recovery-rootfs.squashfs.sig ] || exit 4\nexec /usr/bin/xaac-agent recovery factory-reset --policy \"$POLICY\" --state \"$STATE\" --require-confirmation\n"""
        first_runner="""#!/bin/sh\nset -eu\nexec /usr/bin/xaac-agent recovery factory-reset-first-boot --policy /etc/xaac/recovery/factory-reset.json --state /var/lib/xaac-recovery/factory-reset-state.json\n"""
        contents=(json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+"\n",json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+"\n",service,first_service,runner,first_runner)
        modes=(0o640,0o640,0o644,0o644,0o750,0o750)
        for p,c,m in zip(targets,contents,modes,strict=True): self._write(p,c,m)
        return targets
