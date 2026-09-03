"""Audio detection, validation and rootfs configuration for Dell Wyse 3040."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml

class AudioSupportError(RuntimeError):
    """Raised when audio inspection or configuration is invalid or unsafe."""

@dataclass(frozen=True, slots=True)
class AudioDevice:
    card_index: int
    card_id: str
    description: str
    outputs: tuple[str, ...]
    inputs: tuple[str, ...]
    def to_dict(self) -> dict[str, object]:
        return {"card_index": self.card_index, "card_id": self.card_id, "description": self.description, "outputs": list(self.outputs), "inputs": list(self.inputs)}

@dataclass(frozen=True, slots=True)
class AudioInventory:
    alsa_available: bool
    loaded_modules: tuple[str, ...]
    devices: tuple[AudioDevice, ...]
    pipewire_available: bool
    def to_dict(self) -> dict[str, object]:
        return {"alsa_available": self.alsa_available, "loaded_modules": list(self.loaded_modules), "devices": [d.to_dict() for d in self.devices], "pipewire_available": self.pipewire_available}

@dataclass(frozen=True, slots=True)
class AudioCheck:
    name: str; status: str; expected: str; actual: str
    def to_dict(self) -> dict[str, str]: return {"name": self.name, "status": self.status, "expected": self.expected, "actual": self.actual}

@dataclass(frozen=True, slots=True)
class AudioReport:
    profile: str; compatible: bool; inventory: AudioInventory; checks: tuple[AudioCheck, ...]
    def to_dict(self) -> dict[str, object]: return {"profile": self.profile, "compatible": self.compatible, "inventory": self.inventory.to_dict(), "checks": [c.to_dict() for c in self.checks]}

class AudioDetector:
    def __init__(self, *, root: Path = Path("/")) -> None: self.root = root
    def _read(self, rel: str) -> str | None:
        try: return (self.root / rel.lstrip("/")).read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError): return None
    def detect(self) -> AudioInventory:
        cards = self._read("proc/asound/cards")
        modules_text = self._read("proc/modules") or ""
        modules = tuple(sorted({line.split()[0] for line in modules_text.splitlines() if line.strip()}))
        devices: list[AudioDevice] = []
        if cards:
            for line in cards.splitlines():
                match = re.match(r"\s*(\d+)\s+\[([^]]+)\]:\s*(.+)", line)
                if not match: continue
                idx, card_id, desc = int(match.group(1)), match.group(2).strip(), match.group(3).strip()
                low = f"{card_id} {desc}".lower()
                outputs: list[str] = []
                inputs: list[str] = []
                if any(x in low for x in ("hdmi", "displayport", "display port")): outputs.append("hdmi")
                if any(x in low for x in ("analog", "headphone", "codec", "pch")): outputs.append("analog")
                if any(x in low for x in ("mic", "microphone", "capture", "codec", "pch")): inputs.append("microphone")
                devices.append(AudioDevice(idx, card_id, desc, tuple(outputs), tuple(inputs)))
        pipewire = (self.root / "usr/bin/pipewire").exists() or (self.root / "usr/bin/wireplumber").exists()
        return AudioInventory(cards is not None, modules, tuple(devices), pipewire)

def load_audio_profile(path: Path) -> dict[str, Any]:
    try: raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc: raise AudioSupportError(f"No s'ha pogut carregar el perfil d'àudio: {exc}") from exc
    required = ("alsa", "outputs", "inputs", "pipewire", "configuration")
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("profile"), str) or not all(isinstance(raw.get(k), dict) for k in required):
        raise AudioSupportError("Perfil d'àudio invàlid o esquema no suportat")
    return raw

def compare_audio(inventory: AudioInventory, profile: dict[str, Any]) -> AudioReport:
    checks: list[AudioCheck] = []
    def add(name: str, ok: bool, expected: object, actual: object, *, warning: bool=False) -> None:
        checks.append(AudioCheck(name, "pass" if ok else ("warning" if warning else "fail"), str(expected), str(actual)))
    alsa_required = bool(profile["alsa"].get("required", True))
    add("alsa", inventory.alsa_available, "available", inventory.alsa_available, warning=not alsa_required)
    expected_modules = tuple(str(x) for x in profile["alsa"].get("modules", []))
    module_ok = any(m in inventory.loaded_modules for m in expected_modules)
    add("kernel-module", module_ok, expected_modules, inventory.loaded_modules, warning=not inventory.alsa_available)
    outputs = {o for d in inventory.devices for o in d.outputs}
    for output in profile["outputs"].get("required_types", []): add(f"output-{output}", output in outputs, output, sorted(outputs) or "absent")
    for output in profile["outputs"].get("optional_types", []): add(f"output-{output}", output in outputs, output, sorted(outputs) or "absent", warning=True)
    inputs = {i for d in inventory.devices for i in d.inputs}
    for input_type in profile["inputs"].get("optional_types", []): add(f"input-{input_type}", input_type in inputs, input_type, sorted(inputs) or "absent", warning=True)
    if bool(profile["pipewire"].get("enabled", True)): add("pipewire", inventory.pipewire_available, "installed", inventory.pipewire_available, warning=True)
    return AudioReport(str(profile["profile"]), not any(c.status == "fail" for c in checks), inventory, tuple(checks))

@dataclass(frozen=True, slots=True)
class AudioConfigurationPlan:
    rootfs: Path; files: tuple[tuple[PurePosixPath, str, int], ...]; packages: tuple[str, ...]
    def to_manifest(self) -> dict[str, object]: return {"files": [str(x[0]) for x in self.files], "packages": list(self.packages)}

def create_audio_configuration_plan(rootfs: Path, profile_path: Path) -> AudioConfigurationPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"): raise AudioSupportError(f"Rootfs insegur: {root}")
    profile = load_audio_profile(profile_path)
    cfg = profile["configuration"]
    modules = tuple(str(x) for x in profile["alsa"].get("modules", []))
    files = (
        (PurePosixPath(str(cfg["modules_file"])), "\n".join(modules) + "\n", 0o644),
        (PurePosixPath(str(cfg["modprobe_file"])), "options snd_hda_intel power_save=1\n", 0o644),
        (PurePosixPath(str(cfg["profile_file"])), "backend=pipewire\ndefault_output=auto\ndefault_input=auto\n", 0o644),
    )
    return AudioConfigurationPlan(root, files, tuple(str(x) for x in profile["pipewire"].get("packages", [])))

class AudioConfigurator:
    def execute(self, plan: AudioConfigurationPlan, *, dry_run: bool=False) -> tuple[Path, ...]:
        if dry_run: return ()
        written: list[Path] = []
        for rel, content, mode in plan.files:
            target = plan.rootfs / str(rel).lstrip("/")
            if target.is_symlink(): raise AudioSupportError(f"No s'escriu sobre un enllaç simbòlic: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".tmp")
            temp.write_text(content, encoding="utf-8"); temp.chmod(mode); temp.replace(target); written.append(target)
        return tuple(written)

def write_audio_report(report: AudioReport, destination: Path) -> None:
    if destination.is_symlink(): raise AudioSupportError(f"No s'escriu sobre un enllaç simbòlic: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(destination)
