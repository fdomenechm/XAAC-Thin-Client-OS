"""RustDesk system service configuration for phase 8.4."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class RustDeskServiceError(RuntimeError):
    """Raised when the RustDesk service profile is invalid or unsafe."""

def _path(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise RustDeskServiceError(f"Ruta insegura: {field}")
    return path

def load_rustdesk_service_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RustDeskServiceError(f"No s'ha pogut carregar el servei RustDesk: {exc}") from exc
    expected = {"schema_version", "service", "dependencies", "sandbox", "outputs"}
    if not isinstance(raw, dict) or set(raw) != expected or raw["schema_version"] != 1:
        raise RustDeskServiceError("Esquema del servei RustDesk invàlid")
    service = raw["service"]
    required = {"name","description","user","group","executable","arguments","restart","restart_sec","start_limit_interval_sec","start_limit_burst","timeout_stop_sec"}
    if not isinstance(service, dict) or set(service) != required:
        raise RustDeskServiceError("Definició del servei RustDesk incompleta")
    if service["name"] != "rustdesk-xaac.service" or service["restart"] not in {"no","on-failure","always"}:
        raise RustDeskServiceError("Política del servei RustDesk invàlida")
    for key in ("user","group","description"):
        if not isinstance(service[key], str) or not service[key].strip():
            raise RustDeskServiceError(f"Camp del servei RustDesk invàlid: {key}")
    _path(service["executable"], "executable")
    if not isinstance(service["arguments"], list) or not all(isinstance(x, str) and x for x in service["arguments"]):
        raise RustDeskServiceError("Arguments RustDesk invàlids")
    for key in ("restart_sec","start_limit_interval_sec","start_limit_burst","timeout_stop_sec"):
        if not isinstance(service[key], int) or service[key] < 1:
            raise RustDeskServiceError(f"Valor temporal RustDesk invàlid: {key}")
    deps = raw["dependencies"]
    if not isinstance(deps, dict) or set(deps) != {"after","wants","requires_paths"}:
        raise RustDeskServiceError("Dependències RustDesk incompletes")
    if not all(isinstance(deps[k], list) and all(isinstance(x, str) and x for x in deps[k]) for k in ("after","wants","requires_paths")):
        raise RustDeskServiceError("Dependències RustDesk invàlides")
    for item in deps["requires_paths"]: _path(item, "requires_paths")
    sandbox = raw["sandbox"]
    keys = {"no_new_privileges","private_tmp","protect_system","protect_home","protect_kernel_tunables","protect_kernel_modules","protect_control_groups","restrict_suid_sgid","lock_personality","memory_deny_write_execute","capability_bounding_set","read_write_paths"}
    if not isinstance(sandbox, dict) or set(sandbox) != keys or sandbox["protect_system"] not in {"full","strict"}:
        raise RustDeskServiceError("Sandbox RustDesk invàlid")
    for key in keys - {"protect_system","capability_bounding_set","read_write_paths"}:
        if not isinstance(sandbox[key], bool): raise RustDeskServiceError(f"Sandbox RustDesk invàlid: {key}")
    if not isinstance(sandbox["capability_bounding_set"], list) or not isinstance(sandbox["read_write_paths"], list):
        raise RustDeskServiceError("Llistes de sandbox RustDesk invàlides")
    for item in sandbox["read_write_paths"]: _path(item, "read_write_paths")
    outputs = raw["outputs"]
    if not isinstance(outputs, dict) or set(outputs) != {"unit","sysusers","tmpfiles","state"}:
        raise RustDeskServiceError("Eixides del servei RustDesk incompletes")
    for key, value in outputs.items(): _path(value, key)
    return raw

@dataclass(frozen=True, slots=True)
class RustDeskServicePlan:
    rootfs: Path
    profile: dict[str, Any]
    def target(self, key: str) -> Path:
        p = _path(self.profile["outputs"][key], key)
        return self.rootfs / p.relative_to("/")

def create_rustdesk_service_plan(rootfs: Path, profile_path: Path) -> RustDeskServicePlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise RustDeskServiceError(f"Rootfs insegur: {root}")
    return RustDeskServicePlan(root, load_rustdesk_service_profile(profile_path))

class RustDeskServiceInstaller:
    @staticmethod
    def _write(path: Path, text: str, mode: int) -> None:
        if path.is_symlink(): raise RustDeskServiceError(f"No s'operarà sobre un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8"); tmp.chmod(mode); tmp.replace(path)
    def install(self, plan: RustDeskServicePlan, *, dry_run: bool=False) -> tuple[Path, ...]:
        if dry_run: return ()
        p = plan.profile; s=p["service"]; d=p["dependencies"]; x=p["sandbox"]
        unit = ["[Unit]",f"Description={s['description']}",f"After={' '.join(d['after'])}",f"Wants={' '.join(d['wants'])}"]
        unit += [f"ConditionPathExists={v}" for v in d["requires_paths"]]
        unit += ["","[Service]",f"Type=simple",f"User={s['user']}",f"Group={s['group']}","ExecStart="+" ".join([s['executable'],*s['arguments']]),f"Restart={s['restart']}",f"RestartSec={s['restart_sec']}s",f"TimeoutStopSec={s['timeout_stop_sec']}s",f"StartLimitIntervalSec={s['start_limit_interval_sec']}",f"StartLimitBurst={s['start_limit_burst']}",f"NoNewPrivileges={'true' if x['no_new_privileges'] else 'false'}",f"PrivateTmp={'true' if x['private_tmp'] else 'false'}",f"ProtectSystem={x['protect_system']}",f"ProtectHome={'true' if x['protect_home'] else 'false'}",f"ProtectKernelTunables={'true' if x['protect_kernel_tunables'] else 'false'}",f"ProtectKernelModules={'true' if x['protect_kernel_modules'] else 'false'}",f"ProtectControlGroups={'true' if x['protect_control_groups'] else 'false'}",f"RestrictSUIDSGID={'true' if x['restrict_suid_sgid'] else 'false'}",f"LockPersonality={'true' if x['lock_personality'] else 'false'}",f"MemoryDenyWriteExecute={'true' if x['memory_deny_write_execute'] else 'false'}","CapabilityBoundingSet="+" ".join(x['capability_bounding_set']),"ReadWritePaths="+" ".join(x['read_write_paths']),"","[Install]","WantedBy=multi-user.target",""]
        paths=(plan.target("unit"),plan.target("sysusers"),plan.target("tmpfiles"),plan.target("state"))
        self._write(paths[0],"\n".join(unit),0o644)
        self._write(paths[1],f"u {s['user']} - \"XAAC RustDesk service\" /var/lib/xaac/rustdesk /usr/sbin/nologin\ng {s['group']} -\n",0o644)
        self._write(paths[2],f"d /var/lib/xaac/rustdesk 0750 {s['user']} {s['group']} -\nd /run/xaac/rustdesk 0750 {s['user']} {s['group']} -\n",0o644)
        state={"schema_version":1,"service":s["name"],"enabled":False,"activation":"on-demand","restart":s["restart"],"sandboxed":True}
        self._write(paths[3],json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+"\n",0o640)
        return paths
