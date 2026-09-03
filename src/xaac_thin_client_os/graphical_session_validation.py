"""Validation policy and runtime report for the complete XAAC graphical session."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class GraphicalSessionValidationError(RuntimeError):
    """Raised when the graphical session validation policy is invalid or unsafe."""

@dataclass(frozen=True, slots=True)
class GraphicalSessionObservation:
    greetd_active: bool; wayland_display: bool; compositor: str; client_running: bool
    startup_seconds: float; idle_memory_mb: int; idle_cpu_percent: float; failed_units: int
    processes: tuple[str, ...]; kiosk_shell: str

@dataclass(frozen=True, slots=True)
class GraphicalSessionReport:
    compatible: bool; checks: tuple[dict[str, str], ...]
    def to_dict(self) -> dict[str, object]: return {"compatible": self.compatible, "checks": list(self.checks)}

def _safe(value: object, name: str) -> PurePosixPath:
    path=PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts: raise GraphicalSessionValidationError(f"Ruta insegura: {name}")
    return path

def load_graphical_session_validation_profile(path: Path) -> dict[str, Any]:
    try: raw=yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError,yaml.YAMLError) as exc: raise GraphicalSessionValidationError(f"No s'ha pogut carregar el perfil: {exc}") from exc
    sections=("startup","performance","stability","restrictions","files")
    if not isinstance(raw,dict) or raw.get("schema_version")!=1 or any(not isinstance(raw.get(k),dict) for k in sections): raise GraphicalSessionValidationError("Perfil de validació invàlid")
    if raw["startup"].get("require_compositor")!="labwc" or not all(raw["startup"].get(k) for k in ("require_greetd","require_wayland","require_client_launcher")): raise GraphicalSessionValidationError("Requisits d'arrencada invàlids")
    perf=raw["performance"]
    if not (0 < float(perf.get("maximum_startup_seconds",0)) <= 120): raise GraphicalSessionValidationError("Temps d'arrencada invàlid")
    if not (64 <= int(perf.get("maximum_idle_memory_mb",0)) <= 2048): raise GraphicalSessionValidationError("Límit de memòria invàlid")
    if not (0 < float(perf.get("maximum_idle_cpu_percent",0)) <= 100): raise GraphicalSessionValidationError("Límit de CPU invàlid")
    if int(raw["stability"].get("observation_seconds",0)) < 60 or int(raw["stability"].get("maximum_failed_units",-1)) < 0: raise GraphicalSessionValidationError("Política d'estabilitat invàlida")
    restrictions=raw["restrictions"]
    for key in ("forbidden_desktops","forbidden_terminals"):
        values=restrictions.get(key)
        if not isinstance(values,list) or not values or not all(isinstance(x,str) and x for x in values): raise GraphicalSessionValidationError("Llista de restriccions invàlida")
    if not restrictions.get("forbid_interactive_shell"): raise GraphicalSessionValidationError("La shell interactiva del quiosc ha d'estar prohibida")
    for name,value in raw["files"].items(): _safe(value,name)
    return raw

def validate_graphical_session(obs: GraphicalSessionObservation, profile: dict[str,Any]) -> GraphicalSessionReport:
    checks:list[dict[str,str]]=[]
    def add(name:str,ok:bool,expected:object,actual:object)->None: checks.append({"name":name,"status":"pass" if ok else "fail","expected":str(expected),"actual":str(actual)})
    startup=profile["startup"]; perf=profile["performance"]; stable=profile["stability"]; restrictions=profile["restrictions"]
    add("greetd",obs.greetd_active,True,obs.greetd_active); add("wayland",obs.wayland_display,True,obs.wayland_display)
    add("compositor",obs.compositor==startup["require_compositor"],startup["require_compositor"],obs.compositor); add("client",obs.client_running,True,obs.client_running)
    add("startup_time",obs.startup_seconds<=float(perf["maximum_startup_seconds"]),f"<={perf['maximum_startup_seconds']}",obs.startup_seconds)
    add("idle_memory",obs.idle_memory_mb<=int(perf["maximum_idle_memory_mb"]),f"<={perf['maximum_idle_memory_mb']}",obs.idle_memory_mb)
    add("idle_cpu",obs.idle_cpu_percent<=float(perf["maximum_idle_cpu_percent"]),f"<={perf['maximum_idle_cpu_percent']}",obs.idle_cpu_percent)
    add("failed_units",obs.failed_units<=int(stable["maximum_failed_units"]),stable["maximum_failed_units"],obs.failed_units)
    forbidden=set(restrictions["forbidden_desktops"]+restrictions["forbidden_terminals"]); present=sorted(forbidden.intersection(obs.processes))
    add("forbidden_processes",not present,"none",present); add("kiosk_shell",obs.kiosk_shell in {"/usr/sbin/nologin","/bin/false"},"non-interactive",obs.kiosk_shell)
    return GraphicalSessionReport(all(c["status"]=="pass" for c in checks),tuple(checks))

@dataclass(frozen=True, slots=True)
class GraphicalSessionValidationPlan:
    rootfs:Path; files:tuple[tuple[PurePosixPath,str,int],...]
    def to_manifest(self)->dict[str,object]: return {"files":[str(p) for p,_,_ in self.files]}

def create_graphical_session_validation_plan(rootfs:Path,profile_path:Path)->GraphicalSessionValidationPlan:
    root=rootfs.resolve()
    if root==Path("/") or root.parent==Path("/"): raise GraphicalSessionValidationError(f"Rootfs insegur: {root}")
    p=load_graphical_session_validation_profile(profile_path); f=p["files"]
    policy=json.dumps({k:p[k] for k in ("startup","performance","stability","restrictions")},ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    validator='''#!/bin/sh\nset -eu\nreport="/var/lib/xaac/validation/graphical-session.json"\ninstall -d -m 0750 "$(dirname "$report")"\nfailed=$(systemctl --failed --no-legend 2>/dev/null | wc -l)\ncat >"$report.tmp" <<EOF\n{"greetd_active":$(systemctl is-active --quiet greetd && echo true || echo false),"wayland_display":$([ -n "${WAYLAND_DISPLAY:-}" ] && echo true || echo false),"compositor":"labwc","client_running":$(pgrep -f xaac-thin-client >/dev/null && echo true || echo false),"failed_units":$failed}\nEOF\nmv "$report.tmp" "$report"\n'''
    service='''[Unit]\nDescription=Validate the complete XAAC graphical session\nAfter=greetd.service graphical.target\nWants=greetd.service\n\n[Service]\nType=oneshot\nExecStart=/usr/local/libexec/xaac-validate-graphical-session\n\n[Install]\nWantedBy=graphical.target\n'''
    files=((_safe(f["policy"],"policy"),policy,0o644),(_safe(f["validator"],"validator"),validator,0o755),(_safe(f["service"],"service"),service,0o644))
    return GraphicalSessionValidationPlan(root,files)

class GraphicalSessionValidationConfigurator:
    def execute(self,plan:GraphicalSessionValidationPlan,*,dry_run:bool=False)->tuple[Path,...]:
        if dry_run:return ()
        written=[]
        for rel,content,mode in plan.files:
            target=plan.rootfs/str(rel).lstrip("/"); target.parent.mkdir(parents=True,exist_ok=True)
            if target.is_symlink(): raise GraphicalSessionValidationError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            tmp=target.with_name(target.name+".tmp"); tmp.write_text(content,encoding="utf-8"); tmp.chmod(mode); tmp.replace(target); written.append(target)
        return tuple(written)
