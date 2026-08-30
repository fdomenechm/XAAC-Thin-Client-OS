"""Minimal kiosk compositor configuration for Wayland with controlled X11 fallback."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class CompositorError(RuntimeError):
    """Raised for invalid or unsafe compositor configuration."""

@dataclass(frozen=True, slots=True)
class CompositorInventory:
    backend: str | None
    process_running: bool
    output_count: int
    widths: tuple[int, ...]
    heights: tuple[int, ...]
    fullscreen: bool
    decorations: bool
    panel_present: bool
    restart_count: int

@dataclass(frozen=True, slots=True)
class CompositorCheck:
    name: str; status: str; expected: str; actual: str
    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "expected": self.expected, "actual": self.actual}

@dataclass(frozen=True, slots=True)
class CompositorReport:
    profile: str; compatible: bool; checks: tuple[CompositorCheck, ...]
    def to_dict(self) -> dict[str, object]:
        return {"profile": self.profile, "compatible": self.compatible, "checks": [c.to_dict() for c in self.checks]}

def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise CompositorError(f"Ruta insegura: {name}")
    return path

def load_compositor_profile(path: Path) -> dict[str, Any]:
    try: raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc: raise CompositorError(f"No s'ha pogut carregar el perfil de compositor: {exc}") from exc
    required = ("wayland", "x11", "packages", "kiosk", "outputs", "restart", "files")
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or any(not isinstance(raw.get(k), dict) for k in required):
        raise CompositorError("Perfil de compositor invàlid o esquema no suportat")
    if raw["wayland"].get("compositor") != "labwc" or raw["x11"].get("window_manager") != "openbox":
        raise CompositorError("labwc i openbox són les implementacions controlades")
    kiosk = raw["kiosk"]
    if kiosk.get("fullscreen") is not True or any(kiosk.get(k) is not False for k in ("decorations", "menus", "keybindings")):
        raise CompositorError("El compositor ha d'estar restringit a pantalla completa")
    restart = raw["restart"]
    if not restart.get("enabled") or int(restart.get("max_attempts", 0)) <= 0 or int(restart.get("backoff_seconds", 0)) < 1:
        raise CompositorError("Política de reinici insegura")
    outputs = raw["outputs"]
    if int(outputs.get("minimum_width", 0)) < 640 or int(outputs.get("minimum_height", 0)) < 480:
        raise CompositorError("Resolució mínima invàlida")
    packages = raw["packages"].get("required")
    if not isinstance(packages, list) or not all(isinstance(x, str) and x for x in packages):
        raise CompositorError("Paquets de compositor invàlids")
    for name, value in raw["files"].items(): _safe_absolute(value, name)
    return raw

def compare_compositor(inv: CompositorInventory, profile: dict[str, Any]) -> CompositorReport:
    checks: list[CompositorCheck] = []
    def add(name: str, ok: bool, expected: object, actual: object) -> None:
        checks.append(CompositorCheck(name, "pass" if ok else "fail", str(expected), str(actual)))
    allowed = {"wayland"} | ({"x11"} if profile["x11"].get("enabled") else set())
    add("backend", inv.backend in allowed, sorted(allowed), inv.backend)
    add("process", inv.process_running, True, inv.process_running)
    add("outputs", inv.output_count >= 1, ">=1", inv.output_count)
    min_w, min_h = int(profile["outputs"]["minimum_width"]), int(profile["outputs"]["minimum_height"])
    resolutions_ok = len(inv.widths) == inv.output_count == len(inv.heights) and all(w >= min_w and h >= min_h for w, h in zip(inv.widths, inv.heights))
    add("resolution", resolutions_ok, f">={min_w}x{min_h}", list(zip(inv.widths, inv.heights)))
    add("fullscreen", inv.fullscreen, True, inv.fullscreen)
    add("decorations", not inv.decorations, False, inv.decorations)
    add("panel", not inv.panel_present, False, inv.panel_present)
    add("restart-limit", inv.restart_count <= int(profile["restart"]["max_attempts"]), f"<={profile['restart']['max_attempts']}", inv.restart_count)
    return CompositorReport(str(profile.get("profile", "minimal-kiosk")), all(c.status == "pass" for c in checks), tuple(checks))

@dataclass(frozen=True, slots=True)
class CompositorPlan:
    rootfs: Path; packages: tuple[str, ...]; forbidden_packages: tuple[str, ...]; files: tuple[tuple[PurePosixPath, str, int], ...]
    def to_manifest(self) -> dict[str, object]:
        return {"packages": list(self.packages), "forbidden_packages": list(self.forbidden_packages), "files": [str(p) for p, _, _ in self.files]}

def create_compositor_plan(rootfs: Path, profile_path: Path) -> CompositorPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"): raise CompositorError(f"Rootfs insegur: {root}")
    p = load_compositor_profile(profile_path); files = p["files"]
    labwc = """<?xml version=\"1.0\"?>\n<labwc_config>\n  <core><decoration>client</decoration><gap>0</gap><reuseOutputMode>yes</reuseOutputMode></core>\n  <placement><policy>center</policy></placement>\n  <keyboard>
    <keybind key=\"A-F4\" />
  </keyboard>
  <mouse>
    <context name=\"Root\">
      <mousebind button=\"Left\" action=\"Press\" />
      <mousebind button=\"Right\" action=\"Press\" />
      <mousebind button=\"Middle\" action=\"Press\" />
    </context>
  </mouse>
  <windowRules>
    <windowRule identifier=\"*\" serverDecoration=\"no\">
      <action name=\"AutoPlace\" policy=\"center\" />
    </windowRule>
    <windowRule identifier=\"org.xaac.thinclient\" serverDecoration=\"no\">
      <action name=\"AutoPlace\" policy=\"center\" />
    </windowRule>
    <windowRule identifier=\"*xfreerdp*\" serverDecoration=\"no\" />
    <windowRule identifier=\"org.xaac.ThinClientDock\" serverDecoration=\"no\" skipTaskbar=\"yes\" skipWindowSwitcher=\"yes\" fixedPosition=\"yes\">
      <action name=\"AutoPlace\" policy=\"center\" />
      <action name=\"MoveToEdge\" direction=\"down\" snapWindows=\"no\" />
    </windowRule>
  </windowRules>\n</labwc_config>\n"""
    autostart = "/usr/local/libexec/xaac-session-supervisor &\n"
    openbox = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<openbox_config xmlns=\"http://openbox.org/3.4/rc\">
  <applications>
    <application class=\"*\"><decor>no</decor></application>
    <application class=\"org.xaac.thinclient\">
      <decor>no</decor>
      <position force=\"yes\"><x>center</x><y>center</y></position>
    </application>
    <application class=\"org.xaac.ThinClientDock\">
      <decor>no</decor>
      <position force=\"yes\"><x>center</x><y>-0</y></position>
    </application>
    <application class=\"*xfreerdp*\"><decor>no</decor></application>
  </applications>
  <keyboard />
  <mouse><context name=\"Root\" /></mouse>
  <desktops><number>1</number></desktops>
</openbox_config>
"""
    policy = json.dumps({"primary": p["wayland"], "fallback": p["x11"], "kiosk": p["kiosk"], "outputs": p["outputs"], "restart": p["restart"]}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    planned = ((_safe_absolute(files["labwc_rc"], "labwc_rc"), labwc, 0o644), (_safe_absolute(files["labwc_autostart"], "labwc_autostart"), autostart, 0o755), (_safe_absolute(files["openbox_rc"], "openbox_rc"), openbox, 0o644), (_safe_absolute(files["policy"], "policy"), policy, 0o644))
    return CompositorPlan(root, tuple(dict.fromkeys(p["packages"]["required"])), tuple(dict.fromkeys(p["packages"].get("forbidden", []))), planned)

class CompositorConfigurator:
    def execute(self, plan: CompositorPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run: return ()
        written: list[Path] = []
        for rel, content, mode in plan.files:
            target = plan.rootfs / str(rel).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink(): raise CompositorError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temp = target.with_name(target.name + ".tmp"); temp.write_text(content, encoding="utf-8"); temp.chmod(mode); temp.replace(target); written.append(target)
        return tuple(written)
