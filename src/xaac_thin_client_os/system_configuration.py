"""Deterministic identity and regional configuration for the Debian rootfs."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import yaml


class SystemConfigurationError(RuntimeError):
    """Raised when the rootfs system configuration cannot be applied."""


_HOSTNAME_RE = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}_[A-Za-z]{2,3}\.UTF-8$")
_TIMEZONE_RE = re.compile(r"^[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)+$")


@dataclass(frozen=True, slots=True)
class SystemConfigurationPlan:
    rootfs: Path
    hostname: str
    timezone: str
    locale: str
    locales: tuple[str, ...]

    def locale_command(self) -> tuple[str, ...]:
        return ("chroot", str(self.rootfs), "/usr/sbin/locale-gen")

    def to_manifest(self) -> dict[str, object]:
        return {
            "rootfs": str(self.rootfs),
            "hostname": self.hostname,
            "timezone": self.timezone,
            "locale": self.locale,
            "generated_locales": list(self.locales),
            "locale_command": list(self.locale_command()),
        }


@dataclass(frozen=True, slots=True)
class SystemConfigurationResult:
    executed: bool
    log_path: Path
    files_written: tuple[Path, ...]
    commands_executed: int


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemConfigurationError(f"{name} ha de ser text no buit")
    return value.strip()


def create_system_configuration_plan(rootfs: Path, config_path: Path) -> SystemConfigurationPlan:
    rootfs = rootfs.resolve()
    if rootfs == Path("/") or rootfs.name != "rootfs" or rootfs.parent.parent.name != "runs":
        raise SystemConfigurationError("Ruta rootfs insegura")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SystemConfigurationError(f"No es pot llegir {config_path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise SystemConfigurationError("config/system.yaml té un esquema no suportat")
    unknown = set(raw) - {"schema_version", "hostname", "timezone", "locale", "fallback_locales"}
    if unknown:
        raise SystemConfigurationError(f"Claus desconegudes en system.yaml: {', '.join(sorted(unknown))}")
    hostname = _text(raw.get("hostname"), "hostname").lower()
    timezone = _text(raw.get("timezone"), "timezone")
    locale = _text(raw.get("locale"), "locale")
    fallbacks = raw.get("fallback_locales", [])
    if not isinstance(fallbacks, list) or not all(isinstance(item, str) for item in fallbacks):
        raise SystemConfigurationError("fallback_locales ha de ser una llista de textos")
    locales = tuple(dict.fromkeys([locale, *(item.strip() for item in fallbacks)]))
    if not _HOSTNAME_RE.fullmatch(hostname):
        raise SystemConfigurationError("hostname no vàlid")
    if not _TIMEZONE_RE.fullmatch(timezone) or ".." in timezone:
        raise SystemConfigurationError("timezone no vàlida")
    if any(not _LOCALE_RE.fullmatch(item) for item in locales):
        raise SystemConfigurationError("locale no vàlida")
    return SystemConfigurationPlan(rootfs, hostname, timezone, locale, locales)


class SystemConfigurator:
    def __init__(
        self,
        *,
        geteuid: Callable[[], int] = os.geteuid,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._geteuid = geteuid
        self._runner = runner

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        if path.is_symlink():
            raise SystemConfigurationError(f"No s'escriurà sobre l'enllaç simbòlic {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def execute(
        self, plan: SystemConfigurationPlan, log_path: Path, *, dry_run: bool = False
    ) -> SystemConfigurationResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        planned = (
            plan.rootfs / "etc/hostname",
            plan.rootfs / "etc/hosts",
            plan.rootfs / "etc/locale.gen",
            plan.rootfs / "etc/default/locale",
            plan.rootfs / "etc/timezone",
            plan.rootfs / "etc/localtime",
        )
        with log_path.open("w", encoding="utf-8") as log:
            log.write(("DRY-RUN" if dry_run else "EXECUTE") + " system configuration\n")
            log.write(f"hostname={plan.hostname}\ntimezone={plan.timezone}\nlocale={plan.locale}\n")
            log.write("command=" + " ".join(plan.locale_command()) + "\n")
            if dry_run:
                return SystemConfigurationResult(False, log_path, planned, 0)
            if self._geteuid() != 0:
                raise SystemConfigurationError("La configuració real requereix privilegis de root")
            required = [
                plan.rootfs / "etc/debian_version",
                plan.rootfs / "usr/sbin/locale-gen",
                plan.rootfs / "usr/share/zoneinfo" / plan.timezone,
            ]
            missing = [str(path) for path in required if not path.exists()]
            if missing:
                raise SystemConfigurationError("Al rootfs falten requisits: " + ", ".join(missing))
            self._write_atomic(plan.rootfs / "etc/hostname", plan.hostname + "\n")
            self._write_atomic(
                plan.rootfs / "etc/hosts",
                "127.0.0.1\tlocalhost\n127.0.1.1\t" + plan.hostname + "\n\n::1\tlocalhost ip6-localhost ip6-loopback\n",
            )
            self._write_atomic(
                plan.rootfs / "etc/locale.gen",
                "".join(f"{item} UTF-8\n" for item in plan.locales),
            )
            self._write_atomic(plan.rootfs / "etc/default/locale", f'LANG="{plan.locale}"\n')
            self._write_atomic(plan.rootfs / "etc/timezone", plan.timezone + "\n")
            localtime = plan.rootfs / "etc/localtime"
            if localtime.exists() or localtime.is_symlink():
                localtime.unlink()
            localtime.symlink_to(Path("/usr/share/zoneinfo") / plan.timezone)
            try:
                self._runner(plan.locale_command(), check=True, stdout=log, stderr=subprocess.STDOUT, text=True)
            except subprocess.CalledProcessError as exc:
                raise SystemConfigurationError(f"locale-gen ha fallat amb codi {exc.returncode}") from exc
            except OSError as exc:
                raise SystemConfigurationError(f"No s'ha pogut executar locale-gen: {exc}") from exc
        return SystemConfigurationResult(True, log_path, planned, 1)
