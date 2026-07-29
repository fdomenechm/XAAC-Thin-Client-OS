"""Transactional reception and application of XAAC device policies (phase 6.6)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class PolicyApplicationError(RuntimeError):
    """Raised when a policy or policy transaction is invalid or unsafe."""


_POLICY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise PolicyApplicationError(f"Ruta de polítiques insegura: {field}")
    return path


def _root(rootfs: Path) -> Path:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise PolicyApplicationError(f"Rootfs insegur: {root}")
    return root


def load_policy_application_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyApplicationError(f"No s'ha pogut carregar el perfil de polítiques: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "policy", "transaction", "paths"} or raw.get("schema_version") != 1:
        raise PolicyApplicationError("Esquema d'aplicació de polítiques invàlid")
    policy = raw["policy"]
    required_policy = {"format", "version", "maximum_bytes", "allowed_sections", "require_digest"}
    if not isinstance(policy, dict) or set(policy) != required_policy:
        raise PolicyApplicationError("Configuració del format de política incompleta")
    if policy["format"] != "xaac-device-policy" or policy["version"] != 1:
        raise PolicyApplicationError("Format o versió de política no compatible")
    if not isinstance(policy["maximum_bytes"], int) or not 4096 <= policy["maximum_bytes"] <= 1048576:
        raise PolicyApplicationError("Límit de política invàlid")
    sections = policy["allowed_sections"]
    if not isinstance(sections, list) or not sections or len(sections) != len(set(sections)) or not all(isinstance(v, str) and v.isidentifier() for v in sections):
        raise PolicyApplicationError("Seccions de política invàlides")
    if policy["require_digest"] is not True:
        raise PolicyApplicationError("La verificació del digest és obligatòria")
    transaction = raw["transaction"]
    required_transaction = {"confirmation_timeout_seconds", "rollback_on_validation_failure", "rollback_on_apply_failure", "retain_revisions"}
    if not isinstance(transaction, dict) or set(transaction) != required_transaction:
        raise PolicyApplicationError("Configuració transaccional incompleta")
    if not 30 <= transaction["confirmation_timeout_seconds"] <= 3600 or not 1 <= transaction["retain_revisions"] <= 10:
        raise PolicyApplicationError("Límits transaccionals invàlids")
    if transaction["rollback_on_validation_failure"] is not True or transaction["rollback_on_apply_failure"] is not True:
        raise PolicyApplicationError("El rollback automàtic és obligatori")
    paths = raw["paths"]
    if not isinstance(paths, dict) or set(paths) != {"configuration", "staging", "active", "rollback", "state", "manifest"}:
        raise PolicyApplicationError("Rutes de polítiques incompletes")
    for key, value in paths.items():
        _absolute(value, f"paths.{key}")
    return raw


def policy_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_policy_document(document: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "format", "policy_id", "revision", "payload", "sha256"}
    if not isinstance(document, dict) or set(document) != required:
        raise PolicyApplicationError("Esquema de política invàlid")
    if document["schema_version"] != profile["policy"]["version"] or document["format"] != profile["policy"]["format"]:
        raise PolicyApplicationError("Format o versió de política no compatible")
    if not isinstance(document["policy_id"], str) or not _POLICY_ID.fullmatch(document["policy_id"]):
        raise PolicyApplicationError("Identificador de política invàlid")
    if not isinstance(document["revision"], int) or document["revision"] < 1:
        raise PolicyApplicationError("Revisió de política invàlida")
    payload = document["payload"]
    if not isinstance(payload, dict) or not payload:
        raise PolicyApplicationError("Payload de política invàlid")
    unknown = set(payload) - set(profile["policy"]["allowed_sections"])
    if unknown:
        raise PolicyApplicationError(f"Seccions de política no autoritzades: {', '.join(sorted(unknown))}")
    if document["sha256"] != policy_digest(payload):
        raise PolicyApplicationError("Digest SHA-256 de la política invàlid")
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) > profile["policy"]["maximum_bytes"]:
        raise PolicyApplicationError("Política massa gran")
    return document


class PolicyApplicationManager:
    def __init__(self, rootfs: Path, profile_path: Path):
        self.root = _root(rootfs)
        self.profile_path = profile_path
        self.profile = load_policy_application_profile(profile_path)

    def _path(self, name: str) -> Path:
        return self.root / _absolute(self.profile["paths"][name], name).relative_to("/")

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any], mode: int = 0o640) -> None:
        if path.is_symlink():
            raise PolicyApplicationError(f"No s'utilitzarà un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, path)

    def install(self, *, dry_run: bool = False) -> tuple[Path, ...]:
        destinations = tuple(self._path(name) for name in ("configuration", "staging", "active", "rollback", "state", "manifest"))
        for destination in destinations:
            if destination.is_symlink():
                raise PolicyApplicationError(f"No s'utilitzarà un enllaç simbòlic: {destination}")
        if dry_run:
            return destinations
        configuration, staging, active, rollback, state, manifest = destinations
        staging.mkdir(parents=True, exist_ok=True, mode=0o750)
        active.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        rollback.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        configuration.parent.mkdir(parents=True, exist_ok=True)
        configuration.write_text(yaml.safe_dump(self.profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
        configuration.chmod(0o640)
        self._atomic_json(state, {"schema_version": 1, "status": "idle", "active_policy": None, "pending_policy": None})
        self._atomic_json(manifest, {"schema_version": 1, "transactional": True, "confirmation_required": True, "rollback": "automatic", "allowed_sections": self.profile["policy"]["allowed_sections"]})
        return destinations

    def stage(self, document: dict[str, Any]) -> Path:
        valid = validate_policy_document(document, self.profile)
        destination = self._path("staging") / f"{valid['policy_id']}-{valid['revision']}.json"
        self._atomic_json(destination, valid)
        self._write_state("staged", pending=valid)
        return destination

    def apply(self, staged: Path) -> Path:
        staging = self._path("staging").resolve()
        candidate = staged.resolve()
        if staging not in candidate.parents or not candidate.is_file():
            raise PolicyApplicationError("La política no pertany a l'àrea de staging")
        document = validate_policy_document(json.loads(candidate.read_text(encoding="utf-8")), self.profile)
        active = self._path("active")
        rollback = self._path("rollback")
        if active.exists():
            rollback.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(active, rollback)
        self._atomic_json(active, document)
        self._write_state("pending_confirmation", pending=document)
        return active

    def confirm(self) -> None:
        active = self._read_optional(self._path("active"))
        if active is None:
            raise PolicyApplicationError("No hi ha cap política activa per confirmar")
        self._write_state("confirmed", active=active)

    def rollback(self) -> Path:
        rollback = self._path("rollback")
        if not rollback.is_file():
            raise PolicyApplicationError("No hi ha cap política anterior per restaurar")
        document = validate_policy_document(json.loads(rollback.read_text(encoding="utf-8")), self.profile)
        active = self._path("active")
        self._atomic_json(active, document)
        self._write_state("rolled_back", active=document)
        return active

    @staticmethod
    def _read_optional(path: Path) -> dict[str, Any] | None:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _write_state(self, status: str, *, active: dict[str, Any] | None = None, pending: dict[str, Any] | None = None) -> None:
        current = self._read_optional(self._path("active")) if active is None else active
        self._atomic_json(self._path("state"), {
            "schema_version": 1,
            "status": status,
            "active_policy": None if current is None else {"policy_id": current["policy_id"], "revision": current["revision"]},
            "pending_policy": None if pending is None else {"policy_id": pending["policy_id"], "revision": pending["revision"]},
        })
