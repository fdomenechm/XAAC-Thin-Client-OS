"""Least-privilege account and sensitive-path policy (phase 9.2)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class AccountPermissionsError(RuntimeError):
    """Raised when the account and permissions policy is invalid or unsafe."""


_ALLOWED_KINDS = {"privileged", "administrator", "kiosk", "service"}
_ALLOWED_LOGINS = {"denied", "console-recovery-only", "local-console-and-authorized-ssh"}
_NAME = re.compile(r"(?:root|[a-z_][a-z0-9_-]{0,30})\Z")
_MODE = re.compile(r"0[0-7]{3}\Z")


def _safe_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise AccountPermissionsError(f"Nom invàlid en {field}")
    return value


def _safe_path(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise AccountPermissionsError(f"Ruta invàlida en {field}")
    path = PurePosixPath(value)
    if not path.is_absolute() or value == "/" or ".." in path.parts:
        raise AccountPermissionsError(f"Ruta insegura en {field}")
    return value


def _objects(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
        raise AccountPermissionsError(f"{key} ha de ser una llista no buida")
    return value


def load_account_permissions(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AccountPermissionsError(f"No s'ha pogut carregar la política: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise AccountPermissionsError("Política d'usuaris i permisos invàlida")
    if not isinstance(raw.get("policy_id"), str) or not raw["policy_id"]:
        raise AccountPermissionsError("policy_id és obligatori")

    accounts = _objects(raw, "accounts")
    groups = _objects(raw, "groups")
    paths = _objects(raw, "sensitive_paths")
    rules = _objects(raw, "separation_rules")
    group_names: set[str] = set()
    for group in groups:
        name = _safe_name(group.get("name"), "groups.name")
        if name in group_names:
            raise AccountPermissionsError(f"Grup duplicat: {name}")
        if group.get("system") is not True:
            raise AccountPermissionsError("Els grups XAAC han de ser de sistema")
        group_names.add(name)

    account_names: set[str] = set()
    for account in accounts:
        name = _safe_name(account.get("name"), "accounts.name")
        if name in account_names:
            raise AccountPermissionsError(f"Usuari duplicat: {name}")
        account_names.add(name)
        if account.get("kind") not in _ALLOWED_KINDS:
            raise AccountPermissionsError(f"Tipus d'usuari no admés: {name}")
        primary = _safe_name(account.get("primary_group"), f"{name}.primary_group")
        if name != "root" and primary not in group_names:
            raise AccountPermissionsError(f"Grup principal desconegut: {primary}")
        supplementary = account.get("supplementary_groups")
        if not isinstance(supplementary, list) or not all(isinstance(item, str) and _NAME.fullmatch(item) for item in supplementary):
            raise AccountPermissionsError(f"Grups suplementaris invàlids: {name}")
        _safe_path(account.get("home"), f"{name}.home")
        _safe_path(account.get("shell"), f"{name}.shell")
        if account.get("interactive_login") not in _ALLOWED_LOGINS or account.get("locked") is not True:
            raise AccountPermissionsError(f"Política de login insegura: {name}")
        if account["kind"] in {"kiosk", "service"} and account["shell"] != "/usr/sbin/nologin":
            raise AccountPermissionsError(f"Compte no interactiu amb shell insegura: {name}")
    required = {"root", "xaac-admin", "xaac-kiosk", "xaac-agent"}
    if account_names != required:
        raise AccountPermissionsError("La política ha de definir exactament els quatre comptes obligatoris")

    rule_ids: set[str] = set()
    for rule in rules:
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id or rule_id in rule_ids:
            raise AccountPermissionsError("Regla de separació sense id únic")
        rule_ids.add(rule_id)
        if rule.get("subject") not in account_names:
            raise AccountPermissionsError(f"Subjecte desconegut en {rule_id}")

    seen_paths: set[str] = set()
    for item in paths:
        value = _safe_path(item.get("path"), "sensitive_paths.path")
        if value in seen_paths:
            raise AccountPermissionsError(f"Ruta sensible duplicada: {value}")
        seen_paths.add(value)
        _safe_name(item.get("owner"), f"{value}.owner")
        _safe_name(item.get("group"), f"{value}.group")
        if not isinstance(item.get("mode"), str) or not _MODE.fullmatch(item["mode"]):
            raise AccountPermissionsError(f"Mode invàlid: {value}")
        if not isinstance(item.get("recursive"), bool):
            raise AccountPermissionsError(f"recursive invàlid: {value}")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"sysusers", "tmpfiles", "policy", "state"}:
        raise AccountPermissionsError("outputs incomplet")
    raw["outputs"] = {key: _safe_path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class AccountPermissionsPlan:
    rootfs: Path
    profile: dict[str, Any]

    def destination(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "policy_id": self.profile["policy_id"],
            "account_count": len(self.profile["accounts"]),
            "group_count": len(self.profile["groups"]),
            "sensitive_path_count": len(self.profile["sensitive_paths"]),
            "separation_rule_count": len(self.profile["separation_rules"]),
        }


def create_account_permissions_plan(rootfs: Path, profile_path: Path) -> AccountPermissionsPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise AccountPermissionsError(f"Rootfs insegur: {root}")
    return AccountPermissionsPlan(root, load_account_permissions(profile_path))


class AccountPermissionsInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise AccountPermissionsError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: AccountPermissionsPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.destination(key) for key in ("sysusers", "tmpfiles", "policy", "state"))
        if dry_run:
            return targets
        accounts = plan.profile["accounts"]
        sysusers = ["# Managed by XAAC Thin Client OS — phase 9.2"]
        for group in plan.profile["groups"]:
            sysusers.append(f"g {group['name']} -")
        for account in accounts:
            if account["name"] == "root":
                continue
            sysusers.append(f"u {account['name']} - \"XAAC {account['kind']}\" {account['home']} {account['shell']}")
            for group in account["supplementary_groups"]:
                sysusers.append(f"m {account['name']} {group}")
        tmpfiles = ["# Managed by XAAC Thin Client OS — phase 9.2"]
        for item in plan.profile["sensitive_paths"]:
            tmpfiles.append(f"d {item['path']} {item['mode'][1:]} {item['owner']} {item['group']} -")
            if item["recursive"]:
                tmpfiles.append(f"Z {item['path']} {item['mode'][1:]} {item['owner']} {item['group']} -")
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {**plan.manifest(), "status": "installed", "root_remote_login": "denied", "least_privilege": True}
        payloads = (
            "\n".join(sysusers) + "\n",
            "\n".join(tmpfiles) + "\n",
            json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        for target, payload, mode in zip(targets, payloads, (0o644, 0o644, 0o640, 0o640), strict=True):
            self._write(target, payload, mode)
        return targets
