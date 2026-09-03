"""Declarative threat and restriction model for the XAAC kiosk session."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class KioskRestrictionError(RuntimeError):
    """Raised when the kiosk restriction policy is invalid or unsafe."""


_ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}
_ALLOWED_MITIGATIONS = {"actions", "shortcuts", "processes", "devices", "sessions"}
_ALLOWED_DEVICE_DECISIONS = {"allow", "deny", "policy"}


def _safe_absolute_path(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise KioskRestrictionError(f"Ruta insegura: {name}")
    return path


def _non_empty_strings(value: object, name: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise KioskRestrictionError(f"Llista invàlida: {name}")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise KioskRestrictionError(f"Valors invàlids: {name}")
    if len(value) != len(set(value)):
        raise KioskRestrictionError(f"Valors duplicats: {name}")
    return value


def load_kiosk_restriction_profile(path: Path) -> dict[str, Any]:
    """Load and strictly validate the phase 5.1 policy."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KioskRestrictionError(f"No s'ha pogut carregar la política: {exc}") from exc

    sections = (
        "policy", "threats", "allowed_actions", "shortcuts", "processes",
        "devices", "sessions", "files",
    )
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise KioskRestrictionError("Esquema de restriccions invàlid")
    if any(section not in raw for section in sections):
        raise KioskRestrictionError("Falten seccions obligatòries")

    policy = raw["policy"]
    if not isinstance(policy, dict):
        raise KioskRestrictionError("Política general invàlida")
    if policy.get("default_decision") != "deny":
        raise KioskRestrictionError("La decisió per defecte ha de ser deny")
    if policy.get("enforcement_mode") != "staged":
        raise KioskRestrictionError("La Fase 5.1 només admet enforcement_mode staged")
    if policy.get("kiosk_user") != "xaac-kiosk":
        raise KioskRestrictionError("L'usuari de quiosc ha de ser xaac-kiosk")
    if not isinstance(policy.get("identifier"), str) or not policy["identifier"].strip():
        raise KioskRestrictionError("Identificador de política invàlid")

    threats = raw["threats"]
    if not isinstance(threats, list) or not threats:
        raise KioskRestrictionError("El model d'amenaces no pot estar buit")
    threat_ids: set[str] = set()
    covered: set[str] = set()
    for threat in threats:
        if not isinstance(threat, dict):
            raise KioskRestrictionError("Amenaça invàlida")
        threat_id = threat.get("id")
        if not isinstance(threat_id, str) or not threat_id or threat_id in threat_ids:
            raise KioskRestrictionError("Identificador d'amenaça invàlid o duplicat")
        threat_ids.add(threat_id)
        if not isinstance(threat.get("description"), str) or not threat["description"].strip():
            raise KioskRestrictionError("Descripció d'amenaça invàlida")
        if threat.get("severity") not in _ALLOWED_SEVERITIES:
            raise KioskRestrictionError("Severitat d'amenaça invàlida")
        mitigations = set(_non_empty_strings(threat.get("mitigations"), "mitigations"))
        if not mitigations <= _ALLOWED_MITIGATIONS:
            raise KioskRestrictionError("Mitigació desconeguda")
        covered.update(mitigations)
    if covered != _ALLOWED_MITIGATIONS:
        raise KioskRestrictionError("El model d'amenaces no cobreix totes les superfícies")

    actions = raw["allowed_actions"]
    if not isinstance(actions, list) or not actions:
        raise KioskRestrictionError("Cal definir accions autoritzades")
    action_ids: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            raise KioskRestrictionError("Acció autoritzada invàlida")
        action_id = action.get("id")
        if not isinstance(action_id, str) or not action_id or action_id in action_ids:
            raise KioskRestrictionError("Identificador d'acció invàlid o duplicat")
        action_ids.add(action_id)
        for field in ("actor", "resource"):
            if not isinstance(action.get(field), str) or not action[field].strip():
                raise KioskRestrictionError(f"Camp d'acció invàlid: {field}")
        _non_empty_strings(action.get("operations"), "operations")

    shortcuts = raw["shortcuts"]
    if not isinstance(shortcuts, dict) or shortcuts.get("default") != "deny":
        raise KioskRestrictionError("La política de dreceres ha de denegar per defecte")
    allowed_shortcuts = _non_empty_strings(shortcuts.get("allowed"), "shortcuts.allowed", allow_empty=True)
    forbidden_shortcuts = _non_empty_strings(shortcuts.get("forbidden"), "shortcuts.forbidden")
    reserved_shortcuts = _non_empty_strings(
        shortcuts.get("reserved_for_administration"), "shortcuts.reserved_for_administration"
    )
    if set(allowed_shortcuts) & (set(forbidden_shortcuts) | set(reserved_shortcuts)):
        raise KioskRestrictionError("Una drecera no pot estar simultàniament autoritzada i restringida")

    processes = raw["processes"]
    if not isinstance(processes, dict) or processes.get("default") != "deny":
        raise KioskRestrictionError("La política de processos ha de denegar per defecte")
    allowed_processes = _non_empty_strings(processes.get("allowed"), "processes.allowed")
    forbidden_processes = _non_empty_strings(processes.get("forbidden"), "processes.forbidden")
    if set(allowed_processes) & set(forbidden_processes):
        raise KioskRestrictionError("Un procés no pot estar autoritzat i prohibit")
    maximum = processes.get("maximum_user_processes")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 8 <= maximum <= 256:
        raise KioskRestrictionError("Límit de processos invàlid")

    devices = raw["devices"]
    if not isinstance(devices, dict) or devices.get("default") != "deny":
        raise KioskRestrictionError("La política de dispositius ha de denegar per defecte")
    classes = devices.get("classes")
    required_classes = {"hid", "smartcard", "camera", "printer", "storage"}
    if not isinstance(classes, dict) or set(classes) != required_classes:
        raise KioskRestrictionError("Classes de dispositiu incompletes")
    if any(decision not in _ALLOWED_DEVICE_DECISIONS for decision in classes.values()):
        raise KioskRestrictionError("Decisió de dispositiu invàlida")
    if classes["storage"] != "deny" or devices.get("automount") is not False:
        raise KioskRestrictionError("L'emmagatzematge i l'automuntatge han d'estar bloquejats")
    _safe_absolute_path(devices.get("policy_source"), "devices.policy_source")

    sessions = raw["sessions"]
    if not isinstance(sessions, dict):
        raise KioskRestrictionError("Política de sessions invàlida")
    graphical = sessions.get("graphical")
    tty = sessions.get("tty")
    remote = sessions.get("remote")
    if not all(isinstance(item, dict) for item in (graphical, tty, remote)):
        raise KioskRestrictionError("Seccions de sessió invàlides")
    graphical_allowed = _non_empty_strings(graphical.get("allowed"), "sessions.graphical.allowed")
    if graphical.get("default") not in graphical_allowed:
        raise KioskRestrictionError("La sessió gràfica per defecte no està autoritzada")
    if graphical.get("switching") is not False or graphical.get("nested") is not False:
        raise KioskRestrictionError("El canvi i les sessions niades han d'estar bloquejats")
    admin_tty = tty.get("administrative_tty")
    if tty.get("kiosk_access") is not False or tty.get("authentication_required") is not True:
        raise KioskRestrictionError("Política TTY insegura")
    if not isinstance(admin_tty, int) or isinstance(admin_tty, bool) or not 1 <= admin_tty <= 12:
        raise KioskRestrictionError("TTY administratiu invàlid")
    if remote.get("kiosk_ssh") is not False or remote.get("administrative_ssh") != "policy":
        raise KioskRestrictionError("Política de sessions remotes insegura")

    files = raw["files"]
    if not isinstance(files, dict) or set(files) != {"policy", "threat_model"}:
        raise KioskRestrictionError("Destinacions de fitxers invàlides")
    for name, value in files.items():
        _safe_absolute_path(value, name)
    return raw


@dataclass(frozen=True, slots=True)
class KioskRestrictionPlan:
    """Files generated from the declarative policy."""

    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]
    threat_count: int
    action_count: int

    def to_manifest(self) -> dict[str, object]:
        return {
            "files": [str(path) for path, _, _ in self.files],
            "threat_count": self.threat_count,
            "action_count": self.action_count,
            "enforcement": "staged",
        }


def create_kiosk_restriction_plan(rootfs: Path, profile_path: Path) -> KioskRestrictionPlan:
    """Create an auditable plan without applying later-phase enforcement."""
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise KioskRestrictionError(f"Rootfs insegur: {root}")
    profile = load_kiosk_restriction_profile(profile_path)
    files = profile["files"]
    effective_policy = {
        key: profile[key]
        for key in ("schema_version", "policy", "allowed_actions", "shortcuts", "processes", "devices", "sessions")
    }
    threat_model = {
        "schema_version": profile["schema_version"],
        "policy_identifier": profile["policy"]["identifier"],
        "threats": profile["threats"],
    }
    generated = (
        (
            _safe_absolute_path(files["policy"], "files.policy"),
            json.dumps(effective_policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            0o640,
        ),
        (
            _safe_absolute_path(files["threat_model"], "files.threat_model"),
            json.dumps(threat_model, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            0o644,
        ),
    )
    return KioskRestrictionPlan(root, generated, len(profile["threats"]), len(profile["allowed_actions"]))


class KioskRestrictionConfigurator:
    """Write the model atomically while rejecting symlink targets."""

    def execute(self, plan: KioskRestrictionPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for relative, content, mode in plan.files:
            target = plan.rootfs / str(relative).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise KioskRestrictionError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            temporary = target.with_name(f"{target.name}.tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(mode)
            temporary.replace(target)
            written.append(target)
        return tuple(written)
