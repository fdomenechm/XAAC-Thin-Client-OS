"""Declarative systemd service hardening (phase 9.3)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class SystemdHardeningError(RuntimeError):
    """Raised when the systemd hardening policy is invalid or unsafe."""


_UNIT = re.compile(r"[a-zA-Z0-9_.@-]+\.service\Z")
_CAP = re.compile(r"CAP_[A-Z0-9_]+\Z")
_AF = re.compile(r"AF_[A-Z0-9_]+\Z")
_ALLOWED_PROTECT_SYSTEM = {"yes", "full", "strict"}
_REQUIRED_TRUE = {
    "no_new_privileges", "private_tmp", "protect_home", "protect_kernel_tunables",
    "protect_kernel_modules", "protect_control_groups", "restrict_suid_sgid",
    "lock_personality", "memory_deny_write_execute", "restrict_realtime",
    "restrict_namespaces",
}


def _safe_path(value: object, field: str, *, allow_root: bool = False) -> str:
    if not isinstance(value, str):
        raise SystemdHardeningError(f"Ruta invàlida en {field}")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or (value == "/" and not allow_root):
        raise SystemdHardeningError(f"Ruta insegura en {field}")
    return value


def load_systemd_hardening(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SystemdHardeningError(f"No s'ha pogut carregar la política: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise SystemdHardeningError("Política de hardening systemd invàlida")
    if not isinstance(raw.get("policy_id"), str) or not raw["policy_id"]:
        raise SystemdHardeningError("policy_id és obligatori")
    defaults = raw.get("defaults")
    if not isinstance(defaults, dict):
        raise SystemdHardeningError("defaults és obligatori")
    for key in _REQUIRED_TRUE:
        if defaults.get(key) is not True:
            raise SystemdHardeningError(f"Control obligatori desactivat: {key}")
    if defaults.get("protect_system") not in _ALLOWED_PROTECT_SYSTEM:
        raise SystemdHardeningError("ProtectSystem invàlid")
    if defaults.get("device_policy") != "closed":
        raise SystemdHardeningError("DevicePolicy ha de ser closed")
    if defaults.get("system_call_architectures") != "native":
        raise SystemdHardeningError("SystemCallArchitectures ha de ser native")
    for key in ("capability_bounding_set", "ambient_capabilities", "system_call_filter"):
        if not isinstance(defaults.get(key), list):
            raise SystemdHardeningError(f"{key} ha de ser una llista")
    filters = defaults["system_call_filter"]
    if "@system-service" not in filters or not {"~@mount", "~@reboot", "~@swap"}.issubset(filters):
        raise SystemdHardeningError("Filtre de syscalls insuficient")
    services = raw.get("services")
    if not isinstance(services, list) or not services:
        raise SystemdHardeningError("services ha de ser una llista no buida")
    units: set[str] = set()
    for service in services:
        if not isinstance(service, dict) or not isinstance(service.get("unit"), str) or not _UNIT.fullmatch(service["unit"]):
            raise SystemdHardeningError("Unitat systemd invàlida")
        if service["unit"] in units:
            raise SystemdHardeningError(f"Unitat duplicada: {service['unit']}")
        units.add(service["unit"])
        for key in ("writable_paths", "address_families", "capabilities", "devices"):
            if not isinstance(service.get(key), list):
                raise SystemdHardeningError(f"{service['unit']}.{key} ha de ser una llista")
        for value in service["writable_paths"]:
            _safe_path(value, f"{service['unit']}.writable_paths")
        for value in service["devices"]:
            _safe_path(value, f"{service['unit']}.devices")
        if not all(isinstance(value, str) and _AF.fullmatch(value) for value in service["address_families"]):
            raise SystemdHardeningError(f"AddressFamilies invàlid: {service['unit']}")
        if not all(isinstance(value, str) and _CAP.fullmatch(value) for value in service["capabilities"]):
            raise SystemdHardeningError(f"Capability invàlida: {service['unit']}")
    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"dropin_root", "policy", "state"}:
        raise SystemdHardeningError("outputs incomplet")
    raw["outputs"] = {key: _safe_path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class SystemdHardeningPlan:
    rootfs: Path
    profile: dict[str, Any]

    def dropin(self, unit: str) -> Path:
        base = self.rootfs / self.profile["outputs"]["dropin_root"].lstrip("/")
        return base / f"{unit}.d/90-xaac-hardening.conf"

    def destination(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "policy_id": self.profile["policy_id"],
            "service_count": len(self.profile["services"]),
            "no_new_privileges": True,
            "device_policy": "closed",
        }


def create_systemd_hardening_plan(rootfs: Path, profile_path: Path) -> SystemdHardeningPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise SystemdHardeningError(f"Rootfs insegur: {root}")
    return SystemdHardeningPlan(root, load_systemd_hardening(profile_path))


class SystemdHardeningInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise SystemdHardeningError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _dropin(defaults: dict[str, Any], service: dict[str, Any]) -> str:
        yes = lambda value: "yes" if value else "no"
        lines = ["# Managed by XAAC Thin Client OS — phase 9.3", "[Service]"]
        mapping = {
            "NoNewPrivileges": yes(defaults["no_new_privileges"]),
            "PrivateTmp": yes(defaults["private_tmp"]),
            "ProtectSystem": defaults["protect_system"],
            "ProtectHome": yes(defaults["protect_home"]),
            "ProtectKernelTunables": yes(defaults["protect_kernel_tunables"]),
            "ProtectKernelModules": yes(defaults["protect_kernel_modules"]),
            "ProtectControlGroups": yes(defaults["protect_control_groups"]),
            "RestrictSUIDSGID": yes(defaults["restrict_suid_sgid"]),
            "LockPersonality": yes(defaults["lock_personality"]),
            "MemoryDenyWriteExecute": yes(defaults["memory_deny_write_execute"]),
            "RestrictRealtime": yes(defaults["restrict_realtime"]),
            "RestrictNamespaces": yes(defaults["restrict_namespaces"]),
            "DevicePolicy": defaults["device_policy"],
            "SystemCallArchitectures": defaults["system_call_architectures"],
            "CapabilityBoundingSet": " ".join(service["capabilities"]),
            "AmbientCapabilities": "",
            "RestrictAddressFamilies": " ".join(service["address_families"]),
            "ReadWritePaths": " ".join(service["writable_paths"]),
            "SystemCallFilter": " ".join(defaults["system_call_filter"]),
        }
        lines.extend(f"{key}={value}" for key, value in mapping.items())
        lines.extend(f"DeviceAllow={device} rw" for device in service["devices"])
        return "\n".join(lines) + "\n"

    def install(self, plan: SystemdHardeningPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        dropins = tuple(plan.dropin(service["unit"]) for service in plan.profile["services"])
        targets = dropins + (plan.destination("policy"), plan.destination("state"))
        if dry_run:
            return targets
        defaults = plan.profile["defaults"]
        for service, target in zip(plan.profile["services"], dropins, strict=True):
            self._write(target, self._dropin(defaults, service), 0o644)
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {**plan.manifest(), "status": "installed", "least_privilege": True}
        self._write(plan.destination("policy"), json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(plan.destination("state"), json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        return targets
