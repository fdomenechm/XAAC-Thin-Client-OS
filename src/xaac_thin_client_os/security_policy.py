"""Base security policy and threat model for XAAC Thin Client OS."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class SecurityPolicyError(RuntimeError):
    """Raised when the base security policy is invalid or unsafe."""


_ALLOWED_LEVELS = {"low", "medium", "high", "critical"}
_ALLOWED_TRUST = {"untrusted", "hostile", "privileged", "managed"}
_ALLOWED_CONTROL_TYPES = {"preventive", "detective", "corrective"}


def _list_of_dicts(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
        raise SecurityPolicyError(f"{key} ha de ser una llista no buida d'objectes")
    return value


def _ids(items: list[dict[str, Any]], key: str) -> set[str]:
    result: set[str] = set()
    for item in items:
        value = item.get("id")
        if not isinstance(value, str) or not value:
            raise SecurityPolicyError(f"Cada element de {key} ha de tindre un id")
        if value in result:
            raise SecurityPolicyError(f"Identificador duplicat en {key}: {value}")
        result.add(value)
    return result


def _safe_output(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise SecurityPolicyError("Les rutes d'eixida han de ser absolutes")
    path = PurePosixPath(value)
    if ".." in path.parts or value == "/":
        raise SecurityPolicyError("Ruta d'eixida insegura")
    return value


@dataclass(frozen=True)
class SecurityPolicyPlan:
    rootfs: Path
    profile: dict[str, Any]
    outputs: dict[str, str]

    def to_manifest(self) -> dict[str, object]:
        return {
            "version": self.profile["version"],
            "policy_id": self.profile["policy_id"],
            "status": self.profile["status"],
            "asset_count": len(self.profile["assets"]),
            "actor_count": len(self.profile["actors"]),
            "surface_count": len(self.profile["attack_surfaces"]),
            "threat_count": len(self.profile["threats"]),
            "control_count": len(self.profile["controls"]),
            "accepted_risk_count": len(self.profile["accepted_risks"]),
            "outputs": dict(self.outputs),
        }


def load_security_policy(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SecurityPolicyError(f"No s'ha pogut carregar la política: {exc}") from exc
    if not isinstance(raw, dict):
        raise SecurityPolicyError("La política ha de ser un objecte YAML")
    if raw.get("version") != 1 or raw.get("status") != "baseline":
        raise SecurityPolicyError("Versió o estat de política no admés")
    if not isinstance(raw.get("policy_id"), str) or not raw["policy_id"]:
        raise SecurityPolicyError("policy_id és obligatori")

    assets = _list_of_dicts(raw, "assets")
    actors = _list_of_dicts(raw, "actors")
    surfaces = _list_of_dicts(raw, "attack_surfaces")
    threats = _list_of_dicts(raw, "threats")
    controls = _list_of_dicts(raw, "controls")
    risks = _list_of_dicts(raw, "accepted_risks")
    asset_ids, actor_ids, surface_ids = _ids(assets, "assets"), _ids(actors, "actors"), _ids(surfaces, "attack_surfaces")
    threat_ids, control_ids, risk_ids = _ids(threats, "threats"), _ids(controls, "controls"), _ids(risks, "accepted_risks")
    del risk_ids

    for item in assets:
        if item.get("criticality") not in _ALLOWED_LEVELS:
            raise SecurityPolicyError("Criticitat d'actiu no admesa")
    for item in actors:
        if item.get("trust") not in _ALLOWED_TRUST:
            raise SecurityPolicyError("Nivell de confiança d'actor no admés")
    for item in controls:
        if item.get("type") not in _ALLOWED_CONTROL_TYPES:
            raise SecurityPolicyError("Tipus de control no admés")
    for threat in threats:
        if threat.get("likelihood") not in _ALLOWED_LEVELS or threat.get("impact") not in _ALLOWED_LEVELS or threat.get("residual_risk") not in _ALLOWED_LEVELS:
            raise SecurityPolicyError("Nivell de risc no admés")
        references = (("actors", actor_ids), ("assets", asset_ids), ("surfaces", surface_ids), ("controls", control_ids))
        for field, allowed in references:
            values = threat.get(field)
            if not isinstance(values, list) or not values or not set(values) <= allowed:
                raise SecurityPolicyError(f"Referència desconeguda en {field} de {threat['id']}")
    for risk in risks:
        if risk.get("threat") not in threat_ids or not risk.get("rationale") or not risk.get("owner") or not risk.get("review"):
            raise SecurityPolicyError("Risc acceptat incomplet o amb amenaça desconeguda")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"policy", "threat_model", "state"}:
        raise SecurityPolicyError("outputs ha de declarar policy, threat_model i state")
    raw["outputs"] = {key: _safe_output(value) for key, value in outputs.items()}
    return raw


def create_security_policy_plan(rootfs: Path, profile_path: Path) -> SecurityPolicyPlan:
    resolved = rootfs.resolve()
    if resolved == Path("/") or len(resolved.parts) < 3:
        raise SecurityPolicyError("Rootfs insegur")
    profile = load_security_policy(profile_path)
    return SecurityPolicyPlan(resolved, profile, dict(profile["outputs"]))


class SecurityPolicyInstaller:
    """Install the validated policy, threat model and Agent state atomically."""

    def install(self, plan: SecurityPolicyPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        destinations = tuple(plan.rootfs / value.lstrip("/") for value in plan.outputs.values())
        if dry_run:
            return destinations
        for destination in destinations:
            if destination.is_symlink():
                raise SecurityPolicyError(f"Destinació amb enllaç simbòlic: {destination}")
        policy = {key: value for key, value in plan.profile.items() if key not in {"threats", "accepted_risks", "outputs"}}
        threat_model = {
            "version": plan.profile["version"],
            "policy_id": plan.profile["policy_id"],
            "threats": plan.profile["threats"],
            "accepted_risks": plan.profile["accepted_risks"],
        }
        state = {"schema_version": 1, **plan.to_manifest(), "status": "installed"}
        payloads = (policy, threat_model, state)
        modes = (0o640, 0o644, 0o640)
        for destination, payload, mode in zip(destinations, payloads, modes, strict=True):
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                    stream.write("\n")
                os.chmod(temporary, mode)
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return destinations
