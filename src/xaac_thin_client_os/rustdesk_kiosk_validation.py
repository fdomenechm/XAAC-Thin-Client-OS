"""RustDesk validation contract for the XAAC kiosk session (phase 8.8)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class RustDeskKioskValidationError(RuntimeError):
    """Raised when the RustDesk kiosk validation contract is invalid."""


def _safe_path(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise RustDeskKioskValidationError(f"Ruta insegura: {field}")
    return path


def load_rustdesk_kiosk_validation_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RustDeskKioskValidationError(f"No s'ha pogut carregar la validació RustDesk: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "validation", "outputs"} or raw["schema_version"] != 1:
        raise RustDeskKioskValidationError("Esquema de validació RustDesk invàlid")
    validation = raw["validation"]
    expected = {"display_backends", "capture", "input", "multimonitor", "kiosk_lockdown", "performance"}
    if not isinstance(validation, dict) or set(validation) != expected:
        raise RustDeskKioskValidationError("Política de validació RustDesk incompleta")
    if validation["display_backends"] != ["wayland", "x11"]:
        raise RustDeskKioskValidationError("S'han de validar Wayland i X11")
    capture = validation["capture"]
    if capture != {"required": True, "mechanisms": ["pipewire", "xdg-desktop-portal", "x11"]}:
        raise RustDeskKioskValidationError("Política de captura invàlida")
    input_policy = validation["input"]
    if input_policy != {"keyboard": True, "pointer": True, "mechanisms": ["uinput", "x11"]}:
        raise RustDeskKioskValidationError("Política d'entrada invàlida")
    monitors = validation["multimonitor"]
    if not isinstance(monitors, dict) or monitors.get("required") is not True or monitors.get("minimum_monitors") != 1 or monitors.get("maximum_monitors") != 2 or monitors.get("dynamic_reconfiguration") is not True:
        raise RustDeskKioskValidationError("Política multimonitor invàlida")
    lockdown = validation["kiosk_lockdown"]
    expected_actions = ["launch-terminal", "switch-application", "close-kiosk", "open-system-menu"]
    if not isinstance(lockdown, dict) or lockdown.get("required") is not True or lockdown.get("forbidden_escape_actions") != expected_actions:
        raise RustDeskKioskValidationError("Política de bloqueig invàlida")
    performance = validation["performance"]
    keys = {"maximum_startup_seconds", "maximum_idle_rss_mib", "maximum_active_cpu_percent", "maximum_input_latency_ms"}
    if not isinstance(performance, dict) or set(performance) != keys or any(not isinstance(performance[key], (int, float)) or performance[key] <= 0 for key in keys):
        raise RustDeskKioskValidationError("Llindars de rendiment invàlids")
    outputs = raw["outputs"]
    if not isinstance(outputs, dict) or set(outputs) != {"policy", "checklist", "report", "state"}:
        raise RustDeskKioskValidationError("Eixides de validació incompletes")
    for key, value in outputs.items():
        _safe_path(value, key)
    return raw


@dataclass(frozen=True, slots=True)
class RustDeskKioskValidationPlan:
    rootfs: Path
    profile: dict[str, Any]

    def target(self, key: str) -> Path:
        path = _safe_path(self.profile["outputs"][key], key)
        return self.rootfs / path.relative_to("/")


def create_rustdesk_kiosk_validation_plan(rootfs: Path, profile_path: Path) -> RustDeskKioskValidationPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise RustDeskKioskValidationError(f"Rootfs insegur: {root}")
    return RustDeskKioskValidationPlan(root, load_rustdesk_kiosk_validation_profile(profile_path))


class RustDeskKioskValidationManager:
    @staticmethod
    def _write(path: Path, data: dict[str, Any], mode: int = 0o640) -> None:
        if path.is_symlink():
            raise RustDeskKioskValidationError(f"No s'operarà sobre un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(mode)
        temporary.replace(path)

    def install(self, plan: RustDeskKioskValidationPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        checklist = {
            "schema_version": 1,
            "checks": ["capture", "keyboard-input", "pointer-input", "multimonitor", "wayland", "x11", "kiosk-lockdown", "performance"],
            "requires_runtime_or_hardware": ["capture", "keyboard-input", "pointer-input", "multimonitor", "wayland", "x11", "performance"],
        }
        state = {"schema_version": 1, "status": "not-run", "passed": None, "updated_at": None}
        paths = (plan.target("policy"), plan.target("checklist"), plan.target("state"))
        if not dry_run:
            self._write(paths[0], {"schema_version": 1, **plan.profile["validation"]})
            self._write(paths[1], checklist)
            self._write(paths[2], state)
        return () if dry_run else paths

    def validate(self, plan: RustDeskKioskValidationPlan, evidence: dict[str, Any], *, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
        required = {"capture", "input", "multimonitor", "backends", "lockdown", "performance"}
        if not isinstance(evidence, dict) or set(evidence) != required:
            raise RustDeskKioskValidationError("Evidència de validació incompleta")
        failures: list[str] = []
        if evidence["capture"].get("available") is not True or evidence["capture"].get("mechanism") not in plan.profile["validation"]["capture"]["mechanisms"]:
            failures.append("capture")
        input_data = evidence["input"]
        if input_data.get("keyboard") is not True or input_data.get("pointer") is not True or input_data.get("mechanism") not in plan.profile["validation"]["input"]["mechanisms"]:
            failures.append("input")
        monitor_data = evidence["multimonitor"]
        count = monitor_data.get("count")
        policy = plan.profile["validation"]["multimonitor"]
        if not isinstance(count, int) or not policy["minimum_monitors"] <= count <= policy["maximum_monitors"] or monitor_data.get("dynamic_reconfiguration") is not True:
            failures.append("multimonitor")
        backend_data = evidence["backends"]
        for backend in plan.profile["validation"]["display_backends"]:
            if backend_data.get(backend) is not True:
                failures.append(backend)
        attempted = evidence["lockdown"].get("attempted_actions")
        blocked = evidence["lockdown"].get("blocked_actions")
        expected_actions = plan.profile["validation"]["kiosk_lockdown"]["forbidden_escape_actions"]
        if attempted != expected_actions or blocked != expected_actions:
            failures.append("kiosk-lockdown")
        perf = evidence["performance"]
        limits = plan.profile["validation"]["performance"]
        metrics = {
            "startup_seconds": "maximum_startup_seconds",
            "idle_rss_mib": "maximum_idle_rss_mib",
            "active_cpu_percent": "maximum_active_cpu_percent",
            "input_latency_ms": "maximum_input_latency_ms",
        }
        for metric, limit in metrics.items():
            value = perf.get(metric)
            if not isinstance(value, (int, float)) or value < 0 or value > limits[limit]:
                failures.append(f"performance:{metric}")
        timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        report = {"schema_version": 1, "status": "passed" if not failures else "failed", "passed": not failures, "failures": failures, "evidence": evidence, "validated_at": timestamp}
        state = {"schema_version": 1, "status": report["status"], "passed": report["passed"], "failure_count": len(failures), "updated_at": timestamp}
        if not dry_run:
            self._write(plan.target("report"), report)
            self._write(plan.target("state"), state)
        return report

    def validate_file(self, plan: RustDeskKioskValidationPlan, evidence_path: Path, *, dry_run: bool = False) -> dict[str, Any]:
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RustDeskKioskValidationError(f"No s'ha pogut carregar l'evidència: {exc}") from exc
        return self.validate(plan, evidence, dry_run=dry_run)
