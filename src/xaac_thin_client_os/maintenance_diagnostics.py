"""Build-time policy for XAAC Thin Client OS maintenance and diagnostics (phase 10.3)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class MaintenanceDiagnosticsError(RuntimeError):
    """Raised when the phase 10.3 maintenance policy is unsafe."""


_ALLOWED_COMMANDS = (
    "status",
    "health",
    "network",
    "storage",
    "services",
    "logs",
    "cleanup",
    "diagnostics",
)
_ACTIVE_REQUIRED_SERVICES = {
    "NetworkManager.service",
    "nftables.service",
    "apparmor.service",
}
_INSTALLED_REQUIRED_SERVICES = {"ssh.service"}
_OPTIONAL_SERVICES = {
    "xaac-agent.service",
    "xaac-vpn-manager.service",
    "xaac-update-recover.service",
}
_REQUIRED_OUTPUTS = {
    "policy",
    "state",
    "admin",
    "runtime",
    "diagnostics_root",
    "tmpfiles",
}
_REQUIRED_PRIVACY_FALSE = (
    "include_configuration_contents",
    "include_private_keys",
    "include_credentials",
    "include_vpn_secrets",
)


def _absolute_path(value: object, field: str, *, allow_root: bool = False) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise MaintenanceDiagnosticsError(f"Ruta insegura en {field}")
    path = PurePosixPath(value)
    if ".." in path.parts or (str(path) == "/" and not allow_root):
        raise MaintenanceDiagnosticsError(f"Ruta insegura en {field}")
    return value


def load_maintenance_diagnostics(path: Path) -> dict[str, Any]:
    """Load and strictly validate the phase 10.3 policy."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MaintenanceDiagnosticsError(
            f"No s'ha pogut carregar la política de manteniment: {exc}"
        ) from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise MaintenanceDiagnosticsError("Política de manteniment invàlida")
    if raw.get("maintenance_id") != "xaac-maintenance" or raw.get("phase") != "10.3":
        raise MaintenanceDiagnosticsError("Identitat de manteniment invàlida")
    if raw.get("hardware_profile") != "wyse3040":
        raise MaintenanceDiagnosticsError("Perfil de maquinari no suportat")

    commands = raw.get("commands")
    if not isinstance(commands, list) or tuple(commands) != _ALLOWED_COMMANDS:
        raise MaintenanceDiagnosticsError("Conjunt o ordre de subordres invàlid")

    limits = raw.get("limits")
    if not isinstance(limits, dict):
        raise MaintenanceDiagnosticsError("Límits de manteniment absents")
    log_lines = limits.get("log_lines")
    if not isinstance(log_lines, int) or isinstance(log_lines, bool) or not 50 <= log_lines <= 2000:
        raise MaintenanceDiagnosticsError("Límit de logs invàlid")
    warning = limits.get("root_warning_percent")
    critical = limits.get("root_critical_percent")
    if (
        not isinstance(warning, int)
        or not isinstance(critical, int)
        or isinstance(warning, bool)
        or isinstance(critical, bool)
        or not 50 <= warning < critical <= 99
    ):
        raise MaintenanceDiagnosticsError("Llindars d'emmagatzematge invàlids")
    maximum = limits.get("diagnostics_max_bytes")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1024 * 1024 <= maximum <= 64 * 1024 * 1024:
        raise MaintenanceDiagnosticsError("Mida màxima del diagnòstic invàlida")
    for key in ("diagnostics_retention_days", "journal_retention_days"):
        value = limits.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 90:
            raise MaintenanceDiagnosticsError(f"Retenció invàlida en limits.{key}")
    journal_max = limits.get("journal_max_bytes")
    if not isinstance(journal_max, int) or isinstance(journal_max, bool) or not 16 * 1024 * 1024 <= journal_max <= 512 * 1024 * 1024:
        raise MaintenanceDiagnosticsError("Límit de journal invàlid")

    services = raw.get("services")
    if not isinstance(services, dict):
        raise MaintenanceDiagnosticsError("Política de serveis absent")
    active_required = services.get("active_required")
    installed_required = services.get("installed_required")
    optional = services.get("optional")
    if (
        not isinstance(active_required, list)
        or set(active_required) != _ACTIVE_REQUIRED_SERVICES
        or len(active_required) != len(_ACTIVE_REQUIRED_SERVICES)
    ):
        raise MaintenanceDiagnosticsError("Serveis actius obligatoris invàlids")
    if (
        not isinstance(installed_required, list)
        or set(installed_required) != _INSTALLED_REQUIRED_SERVICES
        or len(installed_required) != len(_INSTALLED_REQUIRED_SERVICES)
    ):
        raise MaintenanceDiagnosticsError("Serveis instal·lats obligatoris invàlids")
    if not isinstance(optional, list) or set(optional) != _OPTIONAL_SERVICES or len(optional) != len(_OPTIONAL_SERVICES):
        raise MaintenanceDiagnosticsError("Serveis opcionals invàlids")

    privacy = raw.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("sanitize_logs") is not True:
        raise MaintenanceDiagnosticsError("La sanitització de logs és obligatòria")
    if any(privacy.get(key) is not False for key in _REQUIRED_PRIVACY_FALSE):
        raise MaintenanceDiagnosticsError("La política de privacitat no pot relaxar-se")
    forbidden = privacy.get("forbidden_paths")
    if not isinstance(forbidden, list) or len(forbidden) < 5:
        raise MaintenanceDiagnosticsError("Rutes prohibides insuficients")
    privacy["forbidden_paths"] = [
        _absolute_path(value, "privacy.forbidden_paths") for value in forbidden
    ]
    if len(privacy["forbidden_paths"]) != len(set(privacy["forbidden_paths"])):
        raise MaintenanceDiagnosticsError("Rutes prohibides duplicades")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != _REQUIRED_OUTPUTS:
        raise MaintenanceDiagnosticsError("outputs incomplet")
    raw["outputs"] = {
        key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()
    }
    if raw["outputs"]["diagnostics_root"] in privacy["forbidden_paths"]:
        raise MaintenanceDiagnosticsError("El directori de diagnòstic no pot estar prohibit")
    return raw


@dataclass(frozen=True, slots=True)
class MaintenanceDiagnosticsPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "maintenance_id": self.profile["maintenance_id"],
            "phase": self.profile["phase"],
            "hardware_profile": self.profile["hardware_profile"],
            "commands": list(self.profile["commands"]),
            "sanitized_diagnostics": True,
        }


def create_maintenance_diagnostics_plan(
    rootfs: Path, profile_path: Path
) -> MaintenanceDiagnosticsPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise MaintenanceDiagnosticsError(f"Rootfs insegur: {root}")
    return MaintenanceDiagnosticsPlan(root, load_maintenance_diagnostics(profile_path))


class MaintenanceDiagnosticsInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise MaintenanceDiagnosticsError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def install(
        self, plan: MaintenanceDiagnosticsPlan, *, dry_run: bool = False
    ) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in ("policy", "state", "tmpfiles"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(),
            "last_cleanup_at": None,
            "last_diagnostics_at": None,
            "last_diagnostics_bundle": None,
        }
        diagnostics_root = plan.profile["outputs"]["diagnostics_root"]
        tmpfiles = (
            "d /var/lib/xaac-maintenance 0750 root root -\n"
            f"d {diagnostics_root} 0700 root root -\n"
        )
        self._write(
            targets[0],
            json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            0o640,
        )
        self._write(
            targets[1],
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            0o640,
        )
        self._write(targets[2], tmpfiles, 0o644)
        return targets
