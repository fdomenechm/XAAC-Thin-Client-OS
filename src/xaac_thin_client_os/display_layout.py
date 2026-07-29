"""Multimonitor, scaling and hotplug policy for the XAAC graphical session."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class DisplayLayoutError(RuntimeError):
    """Raised for invalid or unsafe display layout configuration."""

@dataclass(frozen=True, slots=True)
class DisplayOutput:
    name: str; connected: bool; primary: bool; width: int; height: int; scale: float; x: int; y: int

@dataclass(frozen=True, slots=True)
class DisplayLayoutReport:
    compatible: bool; checks: tuple[dict[str, str], ...]
    def to_dict(self) -> dict[str, object]: return {"compatible": self.compatible, "checks": list(self.checks)}

def _safe(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts: raise DisplayLayoutError(f"Ruta insegura: {name}")
    return path

def load_display_layout_profile(path: Path) -> dict[str, Any]:
    try: raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc: raise DisplayLayoutError(f"No s'ha pogut carregar el perfil: {exc}") from exc
    required = ("backend", "layout", "scaling", "resolution", "freerdp", "packages", "files")
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or any(not isinstance(raw.get(k), dict) for k in required):
        raise DisplayLayoutError("Perfil de pantalles invàlid")
    if raw["backend"].get("primary") != "wayland" or raw["backend"].get("fallback") != "x11": raise DisplayLayoutError("Backends no controlats")
    if raw["layout"].get("mode") not in {"extend", "mirror"} or not raw["layout"].get("hotplug"): raise DisplayLayoutError("Política de disposició invàlida")
    scaling = raw["scaling"]
    lo, default, hi, step = map(float, (scaling.get("minimum", 0), scaling.get("default", 0), scaling.get("maximum", 0), scaling.get("step", 0)))
    if not (0.5 <= lo <= default <= hi <= 4.0) or step <= 0: raise DisplayLayoutError("Escalat invàlid")
    if int(raw["resolution"].get("minimum_width", 0)) < 640 or int(raw["resolution"].get("minimum_height", 0)) < 480: raise DisplayLayoutError("Resolució mínima invàlida")
    if not raw["freerdp"].get("multimon") or not raw["freerdp"].get("dynamic_resolution"): raise DisplayLayoutError("FreeRDP ha de permetre multimonitor i resolució dinàmica")
    packages = raw["packages"].get("required")
    if not isinstance(packages, list) or not all(isinstance(x, str) and x for x in packages): raise DisplayLayoutError("Paquets invàlids")
    for name, value in raw["files"].items(): _safe(value, name)
    return raw

def compare_display_layout(outputs: tuple[DisplayOutput, ...], profile: dict[str, Any]) -> DisplayLayoutReport:
    connected = tuple(o for o in outputs if o.connected); checks: list[dict[str, str]] = []
    def add(name: str, ok: bool, expected: object, actual: object) -> None: checks.append({"name": name, "status": "pass" if ok else "fail", "expected": str(expected), "actual": str(actual)})
    add("outputs", bool(connected), ">=1", len(connected))
    add("primary", sum(o.primary for o in connected) == 1, "1", sum(o.primary for o in connected))
    mw, mh = int(profile["resolution"]["minimum_width"]), int(profile["resolution"]["minimum_height"])
    add("resolution", all(o.width >= mw and o.height >= mh for o in connected), f">={mw}x{mh}", [(o.width,o.height) for o in connected])
    lo, hi = float(profile["scaling"]["minimum"]), float(profile["scaling"]["maximum"])
    add("scaling", all(lo <= o.scale <= hi for o in connected), f"{lo}..{hi}", [o.scale for o in connected])
    unique_positions = {(o.x,o.y) for o in connected}
    add("layout", len(unique_positions) == len(connected) or len(connected) == 1, "non-overlapping", sorted(unique_positions))
    return DisplayLayoutReport(all(c["status"] == "pass" for c in checks), tuple(checks))

@dataclass(frozen=True, slots=True)
class DisplayLayoutPlan:
    rootfs: Path; packages: tuple[str,...]; files: tuple[tuple[PurePosixPath,str,int],...]
    def to_manifest(self) -> dict[str, object]: return {"packages": list(self.packages), "files": [str(p) for p,_,_ in self.files]}

def create_display_layout_plan(rootfs: Path, profile_path: Path) -> DisplayLayoutPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"): raise DisplayLayoutError(f"Rootfs insegur: {root}")
    p = load_display_layout_profile(profile_path); f = p["files"]
    policy = json.dumps({k:p[k] for k in ("backend","layout","scaling","resolution","freerdp")}, ensure_ascii=False, indent=2, sort_keys=True)+"\n"
    wayland = "#!/bin/sh\nset -eu\n# Apply preferred mode and scale to every connected Wayland output.\nwlr-randr | awk '/^[^ ]/ {print $1}' | while read -r output; do\n  [ -n \"$output\" ] && wlr-randr --output \"$output\" --on --preferred --scale 1\ndone\n"
    x11 = "#!/bin/sh\nset -eu\nxrandr --auto\nprimary=$(xrandr --query | awk '/ connected primary/ {print $1; exit}')\n[ -n \"${primary:-}\" ] || primary=$(xrandr --query | awk '/ connected/ {print $1; exit}')\n[ -z \"${primary:-}\" ] || xrandr --output \"$primary\" --primary\n"
    service = "[Unit]\nDescription=XAAC display hotplug reconciliation\nAfter=graphical-session.target\n\n[Service]\nType=oneshot\nExecStart=/usr/local/libexec/xaac-display-layout-wayland\n\n[Install]\nWantedBy=graphical-session.target\n"
    frdp = "XAAC_FREERDP_MULTIMON=/multimon\nXAAC_FREERDP_DYNAMIC_RESOLUTION=/dynamic-resolution\nXAAC_FREERDP_MONITOR_FLAGS=/multimon /dynamic-resolution\n"
    files = ((_safe(f["policy"],"policy"),policy,0o644),(_safe(f["wayland_script"],"wayland_script"),wayland,0o755),(_safe(f["x11_script"],"x11_script"),x11,0o755),(_safe(f["hotplug_service"],"hotplug_service"),service,0o644),(_safe(f["freerdp_env"],"freerdp_env"),frdp,0o644))
    return DisplayLayoutPlan(root, tuple(dict.fromkeys(p["packages"]["required"])), files)

class DisplayLayoutConfigurator:
    def execute(self, plan: DisplayLayoutPlan, *, dry_run: bool=False) -> tuple[Path,...]:
        if dry_run: return ()
        written=[]
        for rel,content,mode in plan.files:
            target=plan.rootfs/str(rel).lstrip("/"); target.parent.mkdir(parents=True,exist_ok=True)
            if target.is_symlink(): raise DisplayLayoutError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            tmp=target.with_name(target.name+".tmp"); tmp.write_text(content,encoding="utf-8"); tmp.chmod(mode); tmp.replace(target); written.append(target)
        return tuple(written)
