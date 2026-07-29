"""Protected recovery partition configuration for phase 11.5."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class RecoveryPartitionError(RuntimeError):
    """Raised when the recovery partition policy is incomplete or unsafe."""

_REQUIRED_TOOLS={"xaac-agent","dpkg","apt-get","fsck.ext4","lsblk","journalctl"}
_REQUIRED_OUTPUTS={"policy","state","mount_unit","verify_service","verifier","grub"}

def _path(value: object, field: str) -> str:
    if not isinstance(value,str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise RecoveryPartitionError(f"Ruta insegura en {field}")
    return value

def load_recovery_partition(path: Path) -> dict[str,Any]:
    try: raw=yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError,yaml.YAMLError) as exc: raise RecoveryPartitionError(f"No s'ha pogut carregar la partició de recuperació: {exc}") from exc
    if not isinstance(raw,dict) or raw.get("schema_version")!=1: raise RecoveryPartitionError("Política de partició de recuperació invàlida")
    if raw.get("hardware_profile")!="wyse3040": raise RecoveryPartitionError("Perfil de maquinari no suportat")
    part=raw.get("partition")
    if not isinstance(part,dict) or part.get("label")!="XAAC_RECOVERY" or part.get("filesystem")!="ext4" or part.get("read_only") is not True:
        raise RecoveryPartitionError("Partició de recuperació insegura")
    part["mount_point"]=_path(part.get("mount_point"),"partition.mount_point")
    size=part.get("minimum_size_mib")
    if not isinstance(size,int) or isinstance(size,bool) or not 512<=size<=2048: raise RecoveryPartitionError("Mida de partició invàlida")
    image=raw.get("image")
    if not isinstance(image,dict) or image.get("format")!="squashfs" or image.get("require_signature") is not True or image.get("hash_algorithm")!="sha256":
        raise RecoveryPartitionError("Imatge de recuperació no verificable")
    for key in ("path","signature_path"): image[key]=_path(image.get(key),f"image.{key}")
    boot=raw.get("boot")
    args=boot.get("kernel_arguments") if isinstance(boot,dict) else None
    if not isinstance(boot,dict) or boot.get("require_signed_kernel") is not True or not isinstance(args,list) or "root=LABEL=XAAC_RECOVERY" not in args or "ro" not in args:
        raise RecoveryPartitionError("Arrencada de recuperació insegura")
    for key in ("kernel_path","initramfs_path"): boot[key]=_path(boot.get(key),f"boot.{key}")
    tools=raw.get("tools",{}).get("required")
    if not isinstance(tools,list) or set(tools)!=_REQUIRED_TOOLS or len(tools)!=len(set(tools)): raise RecoveryPartitionError("Eines de recuperació incompletes")
    protection=raw.get("protection")
    if not isinstance(protection,dict) or protection.get("automatic_factory_reset") is not False:
        raise RecoveryPartitionError("El factory reset automàtic està prohibit")
    for key in ("immutable_image","prohibit_runtime_write","preserve_identity","preserve_enrollment"):
        if protection.get(key) is not True: raise RecoveryPartitionError(f"Protecció obligatòria desactivada: {key}")
    verification=raw.get("verification")
    if not isinstance(verification,dict) or any(verification.get(k) is not True for k in ("verify_on_build","verify_on_boot","fail_closed")):
        raise RecoveryPartitionError("Verificació de recuperació incompleta")
    outputs=raw.get("outputs")
    if not isinstance(outputs,dict) or set(outputs)!=_REQUIRED_OUTPUTS: raise RecoveryPartitionError("outputs incomplet")
    raw["outputs"]={k:_path(v,f"outputs.{k}") for k,v in outputs.items()}
    return raw

@dataclass(frozen=True,slots=True)
class RecoveryPartitionPlan:
    rootfs: Path
    profile: dict[str,Any]
    def output(self,key:str)->Path: return self.rootfs/self.profile["outputs"][key].lstrip("/")
    def manifest(self)->dict[str,object]:
        return {"schema_version":1,"partition_id":self.profile["partition_id"],"label":self.profile["partition"]["label"],"minimum_size_mib":self.profile["partition"]["minimum_size_mib"],"tool_count":len(self.profile["tools"]["required"]),"read_only":True}

def create_recovery_partition_plan(rootfs:Path,profile_path:Path)->RecoveryPartitionPlan:
    root=rootfs.resolve()
    if root==Path("/") or root.name!="rootfs": raise RecoveryPartitionError(f"Rootfs insegur: {root}")
    return RecoveryPartitionPlan(root,load_recovery_partition(profile_path))

class RecoveryPartitionInstaller:
    @staticmethod
    def _write(path:Path,content:str,mode:int)->None:
        if path.is_symlink(): raise RecoveryPartitionError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream: stream.write(content)
            os.chmod(tmp,mode); os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def install(self,plan:RecoveryPartitionPlan,*,dry_run:bool=False)->tuple[Path,...]:
        order=("policy","state","mount_unit","verify_service","verifier","grub"); targets=tuple(plan.output(k) for k in order)
        if dry_run:return targets
        policy={k:v for k,v in plan.profile.items() if k!="outputs"}
        state={**plan.manifest(),"status":"unverified","last_verified_at":None,"image_hash":None,"last_error":None}
        mount="""[Unit]\nDescription=XAAC protected recovery partition\nBefore=xaac-recovery-partition-verify.service\n\n[Mount]\nWhat=/dev/disk/by-label/XAAC_RECOVERY\nWhere=/recovery\nType=ext4\nOptions=ro,nodev,nosuid,noexec\n\n[Install]\nWantedBy=multi-user.target\n"""
        service="""[Unit]\nDescription=Verify XAAC recovery partition\nRequires=recovery.mount\nAfter=recovery.mount\n\n[Service]\nType=oneshot\nExecStart=/usr/libexec/xaac-recovery-partition-verify\nUser=root\nGroup=root\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=yes\nProtectSystem=strict\nReadWritePaths=/var/lib/xaac-recovery\nLockPersonality=yes\nRestrictRealtime=yes\nUMask=0027\n\n[Install]\nWantedBy=multi-user.target\n"""
        verifier="""#!/bin/sh\nset -eu\nPOLICY=/etc/xaac/recovery/recovery-partition.json\nSTATE=/var/lib/xaac-recovery/recovery-partition-state.json\n[ -r \"$POLICY\" ] || exit 2\n[ -r /usr/lib/xaac/recovery/recovery-rootfs.squashfs ] || exit 3\n[ -r /usr/lib/xaac/recovery/recovery-rootfs.squashfs.sig ] || exit 4\nexec /usr/bin/xaac-agent recovery verify-partition --policy \"$POLICY\" --state \"$STATE\"\n"""
        grub="""#!/bin/sh\nset -eu\ncat <<'ENTRY'\nmenuentry 'XAAC Thin Client OS Recovery Partition' --class xaac --class recovery {\n    search --no-floppy --label XAAC_RECOVERY --set=recovery\n    linux ($recovery)/boot/vmlinuz root=LABEL=XAAC_RECOVERY ro systemd.unit=xaac-recovery.target\n    initrd ($recovery)/boot/initrd.img\n}\nENTRY\n"""
        contents=(json.dumps(policy,ensure_ascii=False,indent=2,sort_keys=True)+"\n",json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+"\n",mount,service,verifier,grub)
        modes=(0o640,0o640,0o644,0o644,0o750,0o750)
        for p,c,m in zip(targets,contents,modes,strict=True): self._write(p,c,m)
        return targets
