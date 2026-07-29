"""Declarative systemd base configuration for a Debian root filesystem."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml


class SystemdConfigurationError(RuntimeError):
    """Raised when the systemd base configuration is invalid or cannot be applied."""


_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.(?:service|socket|target|timer|path|mount)$")
_SIZE_RE = re.compile(r"^[1-9][0-9]*[KMG]$")
_RETENTION_RE = re.compile(r"^[1-9][0-9]*(?:s|min|h|day|week|month)$")
_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9._+-]+/?)*$")


@dataclass(frozen=True, slots=True)
class TmpfilesEntry:
    path: str
    type: str
    mode: str
    user: str
    group: str
    age: str

    def render(self) -> str:
        return f"{self.type} {self.path} {self.mode} {self.user} {self.group} {self.age} -"


@dataclass(frozen=True, slots=True)
class SystemdConfigurationPlan:
    rootfs: Path
    default_target: str
    console_getty: bool
    journald_storage: str
    journald_system_max_use: str
    journald_runtime_max_use: str
    journald_max_retention_sec: str
    journald_compress: bool
    tmpfiles: tuple[TmpfilesEntry, ...]
    enable_services: tuple[str, ...]
    disable_services: tuple[str, ...]
    mask_services: tuple[str, ...]

    @property
    def journald_path(self) -> Path:
        return self.rootfs / "etc/systemd/journald.conf.d/20-xaac.conf"

    @property
    def tmpfiles_path(self) -> Path:
        return self.rootfs / "etc/tmpfiles.d/20-xaac.conf"

    @property
    def default_target_path(self) -> Path:
        return self.rootfs / "etc/systemd/system/default.target"

    def to_manifest(self) -> dict[str, object]:
        return {
            "default_target": self.default_target,
            "console_getty": self.console_getty,
            "journald": {
                "storage": self.journald_storage,
                "system_max_use": self.journald_system_max_use,
                "runtime_max_use": self.journald_runtime_max_use,
                "max_retention_sec": self.journald_max_retention_sec,
                "compress": self.journald_compress,
            },
            "tmpfiles": [entry.render() for entry in self.tmpfiles],
            "enable_services": list(self.enable_services),
            "disable_services": list(self.disable_services),
            "mask_services": list(self.mask_services),
        }


@dataclass(frozen=True, slots=True)
class SystemdConfigurationResult:
    plan: SystemdConfigurationPlan
    log_path: Path
    executed: bool
    files_written: tuple[Path, ...]
    links_created: tuple[Path, ...]


def _load(path: Path) -> dict[str, object]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SystemdConfigurationError(f"No es pot llegir {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemdConfigurationError("La configuració systemd ha de ser un mapa YAML")
    allowed = {"default_target", "console_getty", "journald", "tmpfiles", "enable_services", "disable_services", "mask_services"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise SystemdConfigurationError("Claus desconegudes: " + ", ".join(unknown))
    return payload


def _units(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SystemdConfigurationError(f"{field} ha de ser una llista")
    result: list[str] = []
    for unit in value:
        if not isinstance(unit, str) or not _UNIT_RE.fullmatch(unit) or "/" in unit:
            raise SystemdConfigurationError(f"Unitat systemd no vàlida en {field}: {unit!r}")
        result.append(unit)
    if len(result) != len(set(result)):
        raise SystemdConfigurationError(f"{field} conté unitats duplicades")
    return tuple(result)


def create_systemd_configuration_plan(rootfs: Path, config_path: Path) -> SystemdConfigurationPlan:
    resolved = rootfs.resolve()
    if resolved == Path("/") or resolved.parent == Path("/"):
        raise SystemdConfigurationError(f"Rootfs insegur: {resolved}")
    payload = _load(config_path)
    target = payload.get("default_target")
    if not isinstance(target, str) or not target.endswith(".target") or not _UNIT_RE.fullmatch(target):
        raise SystemdConfigurationError("default_target no és vàlid")
    console = payload.get("console_getty")
    if not isinstance(console, bool):
        raise SystemdConfigurationError("console_getty ha de ser booleà")
    journald = payload.get("journald")
    if not isinstance(journald, dict):
        raise SystemdConfigurationError("journald ha de ser un mapa")
    allowed_j = {"storage", "system_max_use", "runtime_max_use", "max_retention_sec", "compress"}
    if set(journald) - allowed_j:
        raise SystemdConfigurationError("journald conté claus desconegudes")
    storage = journald.get("storage")
    system_max = journald.get("system_max_use")
    runtime_max = journald.get("runtime_max_use")
    retention = journald.get("max_retention_sec")
    compress = journald.get("compress")
    if storage not in {"persistent", "volatile", "auto", "none"}:
        raise SystemdConfigurationError("journald.storage no és vàlid")
    if not isinstance(system_max, str) or not _SIZE_RE.fullmatch(system_max):
        raise SystemdConfigurationError("journald.system_max_use no és vàlid")
    if not isinstance(runtime_max, str) or not _SIZE_RE.fullmatch(runtime_max):
        raise SystemdConfigurationError("journald.runtime_max_use no és vàlid")
    if not isinstance(retention, str) or not _RETENTION_RE.fullmatch(retention):
        raise SystemdConfigurationError("journald.max_retention_sec no és vàlid")
    if not isinstance(compress, bool):
        raise SystemdConfigurationError("journald.compress ha de ser booleà")
    raw_tmp = payload.get("tmpfiles")
    if not isinstance(raw_tmp, list):
        raise SystemdConfigurationError("tmpfiles ha de ser una llista")
    entries: list[TmpfilesEntry] = []
    for item in raw_tmp:
        if not isinstance(item, dict) or set(item) != {"path", "type", "mode", "user", "group", "age"}:
            raise SystemdConfigurationError("Cada entrada tmpfiles ha de tindre tots els camps previstos")
        path = item["path"]
        mode = item["mode"]
        if not isinstance(path, str) or not _PATH_RE.fullmatch(path) or ".." in Path(path).parts:
            raise SystemdConfigurationError(f"Ruta tmpfiles no vàlida: {path!r}")
        if item["type"] not in {"d", "D", "v", "q"}:
            raise SystemdConfigurationError("Tipus tmpfiles no admés")
        if not isinstance(mode, str) or not re.fullmatch(r"0[0-7]{3}", mode):
            raise SystemdConfigurationError("Mode tmpfiles no vàlid")
        for key in ("user", "group", "age"):
            if not isinstance(item[key], str) or any(ch.isspace() for ch in item[key]):
                raise SystemdConfigurationError(f"Camp tmpfiles {key} no vàlid")
        entries.append(TmpfilesEntry(path, item["type"], mode, item["user"], item["group"], item["age"]))
    enable = _units(payload.get("enable_services"), "enable_services")
    disable = _units(payload.get("disable_services"), "disable_services")
    mask = _units(payload.get("mask_services"), "mask_services")
    overlap = (set(enable) & set(disable)) | (set(enable) & set(mask)) | (set(disable) & set(mask))
    if overlap:
        raise SystemdConfigurationError("Unitats presents en polítiques incompatibles: " + ", ".join(sorted(overlap)))
    return SystemdConfigurationPlan(resolved, target, console, storage, system_max, runtime_max, retention, compress, tuple(entries), enable, disable, mask)


class SystemdConfigurator:
    def __init__(self, *, geteuid: Callable[[], int] = os.geteuid) -> None:
        self._geteuid = geteuid

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise SystemdConfigurationError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.chmod(0o644)
        tmp.replace(path)

    @staticmethod
    def _link(path: Path, target: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            if path.is_symlink() and os.readlink(path) == target:
                return
            path.unlink()
        path.symlink_to(target)

    @staticmethod
    def _unit_source(rootfs: Path, unit: str) -> Path:
        for base in ("lib/systemd/system", "usr/lib/systemd/system"):
            candidate = rootfs / base / unit
            if candidate.is_file():
                return candidate
        raise SystemdConfigurationError(f"No existeix la unitat systemd requerida: {unit}")

    def execute(self, plan: SystemdConfigurationPlan, log_path: Path, *, dry_run: bool = False) -> SystemdConfigurationResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        files = (plan.journald_path, plan.tmpfiles_path)
        planned_links = [plan.default_target_path]
        planned_links.extend(plan.rootfs / "etc/systemd/system/multi-user.target.wants" / unit for unit in plan.enable_services)
        planned_links.extend(plan.rootfs / "etc/systemd/system" / unit for unit in plan.mask_services)
        if plan.console_getty:
            planned_links.append(plan.rootfs / "etc/systemd/system/getty.target.wants/getty@tty1.service")
        if dry_run:
            log_path.write_text("DRY-RUN\n" + "\n".join([*(f"write {p}" for p in files), *(f"link {p}" for p in planned_links), *(f"disable {u}" for u in plan.disable_services)]) + "\n", encoding="utf-8")
            return SystemdConfigurationResult(plan, log_path, False, (), ())
        if self._geteuid() != 0:
            raise SystemdConfigurationError("La configuració systemd requereix privilegis de root")
        if not (plan.rootfs / "etc/debian_version").is_file() or not (plan.rootfs / "lib/systemd/system").is_dir():
            raise SystemdConfigurationError("El rootfs no conté un sistema Debian amb systemd")
        journald = "[Journal]\n" + f"Storage={plan.journald_storage}\nSystemMaxUse={plan.journald_system_max_use}\nRuntimeMaxUse={plan.journald_runtime_max_use}\nMaxRetentionSec={plan.journald_max_retention_sec}\nCompress={'yes' if plan.journald_compress else 'no'}\n"
        tmpfiles = "# XAAC Thin Client OS\n" + "\n".join(entry.render() for entry in plan.tmpfiles) + "\n"
        self._write_atomic(plan.journald_path, journald)
        self._write_atomic(plan.tmpfiles_path, tmpfiles)
        target_source = self._unit_source(plan.rootfs, plan.default_target)
        links: list[Path] = []
        self._link(plan.default_target_path, "/" + str(target_source.relative_to(plan.rootfs)))
        links.append(plan.default_target_path)
        for unit in plan.enable_services:
            source = self._unit_source(plan.rootfs, unit)
            link = plan.rootfs / "etc/systemd/system/multi-user.target.wants" / unit
            self._link(link, "/" + str(source.relative_to(plan.rootfs)))
            links.append(link)
        for unit in plan.disable_services:
            for wants in ("multi-user.target.wants", "timers.target.wants"):
                link = plan.rootfs / "etc/systemd/system" / wants / unit
                if link.exists() or link.is_symlink():
                    link.unlink()
        for unit in plan.mask_services:
            link = plan.rootfs / "etc/systemd/system" / unit
            self._link(link, "/dev/null")
            links.append(link)
        if plan.console_getty:
            source = self._unit_source(plan.rootfs, "getty@.service")
            link = plan.rootfs / "etc/systemd/system/getty.target.wants/getty@tty1.service"
            self._link(link, "/" + str(source.relative_to(plan.rootfs)))
            links.append(link)
        log_path.write_text("configured systemd base\n" + "\n".join(str(p) for p in (*files, *links)) + "\n", encoding="utf-8")
        return SystemdConfigurationResult(plan, log_path, True, files, tuple(links))
