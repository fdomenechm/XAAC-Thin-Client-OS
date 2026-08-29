"""Directional local integration contract between XAAC Thin Client OS and Agent."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class LocalIntegrationError(RuntimeError):
    """Raised when the local OS/Agent integration contract is invalid."""


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise LocalIntegrationError(f"Ruta d'integració insegura: {field}")
    return path


def _mode(value: object, field: str) -> int:
    try:
        mode = int(str(value), 8)
    except ValueError as exc:
        raise LocalIntegrationError(f"Mode d'integració invàlid: {field}") from exc
    if mode & 0o007:
        raise LocalIntegrationError(f"Mode d'integració massa permissiu: {field}")
    return mode


def load_local_integration_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LocalIntegrationError(f"No s'ha pogut carregar el contracte local: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "contract", "principals", "directories", "limits", "files"}:
        raise LocalIntegrationError("Esquema del contracte local invàlid")
    if raw.get("schema_version") != 2:
        raise LocalIntegrationError("Versió d'esquema local no suportada")

    contract = raw["contract"]
    if not isinstance(contract, dict) or set(contract) != {"name", "version", "thin_client_version", "formats"}:
        raise LocalIntegrationError("Contracte local incomplet")
    if contract["name"] != "xaac-local-integration" or contract["version"] != 1 or contract["thin_client_version"] != "1.1.0":
        raise LocalIntegrationError("Identitat o versió del contracte local invàlida")
    formats = contract["formats"]
    expected_formats = {
        "state": "xaac-state/v2",
        "event": "xaac-local-event/v1",
        "configuration": "xaac-configuration/v1",
        "command": "xaac-local-command/v1",
    }
    if formats != expected_formats:
        raise LocalIntegrationError("Formats del contracte local incompatibles")

    principals = raw["principals"]
    if principals != {"agent_user": "xaac-agent", "thin_client_user": "xaac-kiosk", "shared_group": "xaac-ipc"}:
        raise LocalIntegrationError("Principals del contracte local incompatibles")

    directories = raw["directories"]
    expected = {
        "runtime_parent": ("/run/xaac", "root", "xaac-ipc", 0o750),
        "runtime": ("/run/xaac/thin-client", "xaac-kiosk", "xaac-ipc", 0o2750),
        "events": ("/run/xaac/thin-client/events", "xaac-kiosk", "xaac-ipc", 0o2750),
        "persistent_parent": ("/var/lib/xaac/thin-client", "root", "xaac-ipc", 0o750),
        "state": ("/var/lib/xaac/thin-client/state", "xaac-kiosk", "xaac-ipc", 0o2750),
        "configuration": ("/var/lib/xaac/thin-client/config", "xaac-agent", "xaac-ipc", 0o2750),
        "commands": ("/run/xaac/commands", "xaac-agent", "xaac-ipc", 0o2750),
    }
    if not isinstance(directories, dict) or set(directories) != set(expected):
        raise LocalIntegrationError("Directoris del contracte local incomplets")
    seen: set[str] = set()
    for name, (expected_path, expected_owner, expected_group, expected_mode) in expected.items():
        item = directories[name]
        if not isinstance(item, dict) or set(item) != {"path", "owner", "group", "mode"}:
            raise LocalIntegrationError(f"Directori local invàlid: {name}")
        directory = _absolute(item["path"], f"directories.{name}.path")
        mode = _mode(item["mode"], f"directories.{name}.mode")
        if str(directory) != expected_path or item["owner"] != expected_owner or item["group"] != expected_group or mode != expected_mode:
            raise LocalIntegrationError(f"Política local incompatible: {name}")
        if str(directory) in seen:
            raise LocalIntegrationError("Directoris locals duplicats")
        seen.add(str(directory))

    limits = raw["limits"]
    if not isinstance(limits, dict) or set(limits) != {"state_max_bytes", "event_max_bytes", "max_events", "heartbeat_seconds"}:
        raise LocalIntegrationError("Límits del contracte local incomplets")
    if not 1024 <= limits["state_max_bytes"] <= 1048576 or not 1024 <= limits["event_max_bytes"] <= 1048576:
        raise LocalIntegrationError("Límits de mida locals invàlids")
    if not 1 <= limits["max_events"] <= 4096 or not 5 <= limits["heartbeat_seconds"] <= 300:
        raise LocalIntegrationError("Límits temporals locals invàlids")

    files = raw["files"]
    expected_files = {
        "configuration": "/etc/xaac/local-integration.yaml",
        "tmpfiles": "/usr/lib/tmpfiles.d/xaac-local-integration.conf",
        "manifest": "/etc/xaac/local-integration-manifest.json",
    }
    if not isinstance(files, dict) or files != expected_files:
        raise LocalIntegrationError("Fitxers del contracte local incompatibles")
    for key, value in files.items():
        _absolute(value, f"files.{key}")
    return raw


@dataclass(frozen=True, slots=True)
class LocalIntegrationPlan:
    configuration: Path
    tmpfiles: Path
    manifest: Path

    @property
    def files(self) -> tuple[Path, Path, Path]:
        return self.configuration, self.tmpfiles, self.manifest


class LocalIntegrationConfigurator:
    def install(self, rootfs: Path, profile_path: Path, *, dry_run: bool = False) -> LocalIntegrationPlan:
        root = rootfs.resolve()
        if root == Path("/") or root.parent == Path("/"):
            raise LocalIntegrationError(f"Rootfs insegur: {root}")
        profile = load_local_integration_profile(profile_path)
        destinations = {
            key: root / _absolute(value, key).relative_to("/")
            for key, value in profile["files"].items()
        }
        for destination in destinations.values():
            if destination.is_symlink():
                raise LocalIntegrationError(f"No s'utilitzarà un enllaç simbòlic: {destination}")
        plan = LocalIntegrationPlan(destinations["configuration"], destinations["tmpfiles"], destinations["manifest"])
        if dry_run:
            return plan
        for destination in plan.files:
            destination.parent.mkdir(parents=True, exist_ok=True)

        plan.configuration.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
        plan.configuration.chmod(0o640)

        lines: list[str] = []
        for item in profile["directories"].values():
            lines.append(f"d {item['path']} {item['mode']} {item['owner']} {item['group']} -")
        plan.tmpfiles.write_text("\n".join(lines) + "\n", encoding="utf-8")
        plan.tmpfiles.chmod(0o644)

        d = profile["directories"]
        manifest = {
            "schema_version": 1,
            "contract": "xaac-local-integration/v1",
            "thin_client": {"package": "xaac-thinclient", "version": profile["contract"]["thin_client_version"]},
            "formats": profile["contract"]["formats"],
            "principals": profile["principals"],
            "paths": {
                "runtime": d["runtime"]["path"],
                "events": d["events"]["path"],
                "state": d["state"]["path"],
                "configuration": d["configuration"]["path"],
                "commands": d["commands"]["path"],
            },
            "separation": {
                "state": "xaac-kiosk-writes-xaac-agent-reads",
                "events": "xaac-kiosk-writes-xaac-agent-reads",
                "configuration": "xaac-agent-writes-xaac-kiosk-reads",
                "commands": "xaac-agent-writes-xaac-kiosk-reads",
            },
            "limits": profile["limits"],
        }
        plan.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        plan.manifest.chmod(0o640)
        return plan
