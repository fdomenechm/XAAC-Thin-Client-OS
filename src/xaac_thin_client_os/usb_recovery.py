"""Signed USB recovery configuration for phase 11.7."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class UsbRecoveryError(RuntimeError):
    """Raised when the USB recovery policy is incomplete or unsafe."""

_REQUIRED_OUTPUTS={"policy","state","udev_rule","service","runner"}

def _path(value: object, field: str) -> str:
    if not isinstance(value,str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise UsbRecoveryError(f"Ruta insegura en {field}")
    return value

def load_usb_recovery(path: Path) -> dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError,yaml.YAMLError) as exc: raise UsbRecoveryError(f"No s'ha pogut carregar la política de recuperació USB: {exc}") from exc
    if not isinstance(raw,dict) or raw.get("schema_version")!=1: raise UsbRecoveryError("Política de recuperació USB invàlida")
    if raw.get("hardware_profile")!="wyse3040": raise UsbRecoveryError("Perfil de maquinari no suportat")
    detection=raw.get("detection")
    if not isinstance(detection,dict) or detection.get("filesystem_labels")!=["XAAC_RECOVERY_USB"] or detection.get("removable_only") is not True or detection.get("read_only_mount") is not True:
        raise UsbRecoveryError("Detecció USB insegura")
    opts=detection.get("mount_options")
    if not isinstance(opts,list) or not {"ro","nodev","nosuid","noexec"}.issubset(set(opts)): raise UsbRecoveryError("Opcions de muntatge USB insuficients")
    trust=raw.get("trust")
    if not isinstance(trust,dict) or trust.get("require_manifest") is not True or trust.get("require_signature") is not True or trust.get("hash_algorithm")!="sha256": raise UsbRecoveryError("Confiança del mitjà USB insuficient")
    _path(trust.get("trusted_keyring"),"trust.trusted_keyring")
    version=raw.get("version")
    if not isinstance(version,dict) or version.get("require_product")!="xaac-thin-client-os" or version.get("allow_downgrade") is not False or version.get("require_hardware_profile") is not True or version.get("minimum_schema")!=1:
        raise UsbRecoveryError("Política de versió USB invàlida")
    reinstall=raw.get("reinstallation")
    required_true=("transactional","verify_before_write","verify_after_write","preserve_device_identity","preserve_enrollment","require_ac_power")
    if not isinstance(reinstall,dict) or any(reinstall.get(k) is not True for k in required_true): raise UsbRecoveryError("Reinstal·lació USB insegura")
    for k in ("image","kernel","initramfs"):
        v=reinstall.get(k)
        if not isinstance(v,str) or not v or "/" in v or ".." in v: raise UsbRecoveryError("Fitxer de recuperació USB invàlid")
    errors=raw.get("errors")
    if not isinstance(errors,dict) or any(errors.get(k) is not True for k in ("fail_closed","persistent_log","notify_agent")): raise UsbRecoveryError("Gestió d'errors USB insuficient")
    media=raw.get("incorrect_media")
    if not isinstance(media,dict) or any(media.get(k) is not True for k in ("reject_unknown_label","reject_non_removable","reject_unsigned","reject_wrong_product","reject_wrong_hardware","reject_unsupported_version")):
        raise UsbRecoveryError("Política de mitjà incorrecte insuficient")
    outputs=raw.get("outputs")
    if not isinstance(outputs,dict) or set(outputs)!=_REQUIRED_OUTPUTS: raise UsbRecoveryError("outputs incomplet")
    raw["outputs"]={k:_path(v,f"outputs.{k}") for k,v in outputs.items()}
    return raw

@dataclass(frozen=True,slots=True)
class UsbRecoveryPlan:
    rootfs: Path
    profile: dict[str,Any]
    def output(self,key:str)->Path: return self.rootfs/self.profile["outputs"][key].lstrip("/")
    def manifest(self)->dict[str,object]:
        return {"schema_version":1,"recovery_id":self.profile["recovery_id"],"label":"XAAC_RECOVERY_USB","hash_algorithm":"sha256","signature_required":True,"downgrade_allowed":False}

def create_usb_recovery_plan(rootfs:Path,profile_path:Path)->UsbRecoveryPlan:
    root=rootfs.resolve()
    if root==Path("/") or root.name!="rootfs": raise UsbRecoveryError(f"Rootfs insegur: {root}")
    return UsbRecoveryPlan(root,load_usb_recovery(profile_path))

class UsbRecoveryInstaller:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise UsbRecoveryError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream: stream.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def install(self,plan:UsbRecoveryPlan,*,dry_run:bool=False)->tuple[Path,...]:
        order=("policy","state","udev_rule","service","runner"); targets=tuple(plan.output(k) for k in order)
        if dry_run:return targets
        policy={k:v for k,v in plan.profile.items() if k!="outputs"}
        state={**plan.manifest(),"status":"idle","device":None,"detected_version":None,"last_error":None,"updated_at":None}
        udev='ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="XAAC_RECOVERY_USB", ENV{ID_DRIVE_FLASH_SD}=="1", TAG+="systemd", ENV{SYSTEMD_WANTS}="xaac-usb-recovery@%k.service"\n'
        service="""[Unit]\nDescription=XAAC signed USB recovery for %I\nAfter=systemd-udevd.service\nConditionACPower=true\n\n[Service]\nType=oneshot\nExecStart=/usr/libexec/xaac-usb-recovery /dev/%I\nUser=root\nGroup=root\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=yes\nProtectSystem=strict\nReadWritePaths=/run/xaac-recovery /var/lib/xaac-recovery /var/lib/xaac /etc/xaac\nPrivateDevices=no\nLockPersonality=yes\nRestrictRealtime=yes\nUMask=0027\n"""
        runner="""#!/bin/sh\nset -eu\nDEVICE=${1:?missing block device}\nPOLICY=/etc/xaac/recovery/usb-recovery.json\nSTATE=/var/lib/xaac-recovery/usb-recovery-state.json\n[ -b "$DEVICE" ] || exit 2\n[ -r "$POLICY" ] || exit 3\nexec /usr/bin/xaac-agent recovery usb --device "$DEVICE" --policy "$POLICY" --state "$STATE" --verify-signature --verify-version --transactional\n"""
        contents=(json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+"\n",json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+"\n",udev,service,runner)
        modes=(0o640,0o640,0o644,0o644,0o750)
        for p,c,m in zip(targets,contents,modes,strict=True): self._write(p,c,m)
        return targets
