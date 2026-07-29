"""Ephemeral and restricted kiosk filesystem for phase 5.5."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class KioskFilesystemError(RuntimeError):
    """Raised when the kiosk filesystem policy is invalid or unsafe."""


_SIZE_RE = re.compile(r"^[1-9][0-9]*(?:K|M|G)$")
_MODE_RE = re.compile(r"^0[0-7]{3}$")
_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise KioskFilesystemError(f"Ruta insegura: {name}")
    return path


def load_kiosk_filesystem_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KioskFilesystemError(f"No s'ha pogut carregar la política del sistema de fitxers: {exc}") from exc
    required = {"schema_version", "policy", "home", "runtime", "allowed_directories", "downloads", "permissions", "cleanup", "files"}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or set(raw) != required:
        raise KioskFilesystemError("Esquema del sistema de fitxers del quiosc invàlid")
    policy = raw["policy"]
    if not isinstance(policy, dict) or set(policy) != {"identifier", "default_decision", "enforcement_mode", "kiosk_user"}:
        raise KioskFilesystemError("Política del sistema de fitxers incompleta")
    if policy["default_decision"] != "deny" or policy["enforcement_mode"] != "enforce":
        raise KioskFilesystemError("La política ha de denegar per defecte i aplicar-se")
    if policy["kiosk_user"] != "xaac-kiosk" or not isinstance(policy["identifier"], str):
        raise KioskFilesystemError("Identitat de la política invàlida")
    home = raw["home"]
    expected_home = {"path", "ephemeral", "backing", "mode", "size", "inodes", "clear_on_start", "clear_on_stop"}
    if not isinstance(home, dict) or set(home) != expected_home:
        raise KioskFilesystemError("Configuració del home efímer incompleta")
    if _safe_absolute(home["path"], "home.path") != PurePosixPath("/home/xaac-kiosk"):
        raise KioskFilesystemError("El home del quiosc ha de ser /home/xaac-kiosk")
    if home["ephemeral"] is not True or home["backing"] != "tmpfs" or home["clear_on_start"] is not True or home["clear_on_stop"] is not True:
        raise KioskFilesystemError("El home del quiosc ha de ser efímer i netejar-se")
    if not isinstance(home["mode"], str) or not _MODE_RE.fullmatch(home["mode"]):
        raise KioskFilesystemError("Mode del home invàlid")
    if not isinstance(home["size"], str) or not _SIZE_RE.fullmatch(home["size"]) or not isinstance(home["inodes"], int) or home["inodes"] < 1024:
        raise KioskFilesystemError("Límits del home invàlids")
    runtime = raw["runtime"]
    if not isinstance(runtime, dict) or set(runtime) != {"path", "mode", "size"}:
        raise KioskFilesystemError("Configuració runtime incompleta")
    _safe_absolute(runtime["path"], "runtime.path")
    if not _MODE_RE.fullmatch(str(runtime["mode"])) or not _SIZE_RE.fullmatch(str(runtime["size"])):
        raise KioskFilesystemError("Configuració runtime invàlida")
    directories = raw["allowed_directories"]
    if not isinstance(directories, list) or not directories:
        raise KioskFilesystemError("Cal definir directoris permesos")
    seen: set[PurePosixPath] = set()
    for item in directories:
        if not isinstance(item, dict) or set(item) != {"path", "mode", "purpose"}:
            raise KioskFilesystemError("Directori permés invàlid")
        directory = _safe_absolute(item["path"], "allowed_directories.path")
        if directory in seen or PurePosixPath("/home/xaac-kiosk") not in directory.parents:
            raise KioskFilesystemError("Els directoris permesos han de ser únics i estar dins del home")
        seen.add(directory)
        if not _MODE_RE.fullmatch(str(item["mode"])) or not isinstance(item["purpose"], str) or not item["purpose"]:
            raise KioskFilesystemError("Metadades del directori permés invàlides")
    downloads = raw["downloads"]
    expected_downloads = {"path", "maximum_size", "executable_files", "device_files", "suid_files", "clear_on_session_end"}
    if not isinstance(downloads, dict) or set(downloads) != expected_downloads:
        raise KioskFilesystemError("Política de descàrregues incompleta")
    if _safe_absolute(downloads["path"], "downloads.path") not in seen:
        raise KioskFilesystemError("El directori de descàrregues ha d'estar permés")
    if not _SIZE_RE.fullmatch(str(downloads["maximum_size"])) or any(downloads[key] is not False for key in ("executable_files", "device_files", "suid_files")) or downloads["clear_on_session_end"] is not True:
        raise KioskFilesystemError("Les descàrregues han de ser limitades, no executables i efímeres")
    permissions = raw["permissions"]
    if not isinstance(permissions, dict) or set(permissions) != {"owner", "group", "umask", "follow_symlinks", "world_writable"}:
        raise KioskFilesystemError("Política de permisos incompleta")
    if any(not isinstance(permissions[key], str) or not _USER_RE.fullmatch(permissions[key]) for key in ("owner", "group")) or permissions["owner"] != "xaac-kiosk" or permissions["group"] != "xaac-kiosk":
        raise KioskFilesystemError("Propietari o grup del quiosc invàlid")
    if permissions["umask"] != "0077" or permissions["follow_symlinks"] is not False or permissions["world_writable"] is not False:
        raise KioskFilesystemError("Els permisos del quiosc no són prou restrictius")
    cleanup = raw["cleanup"]
    if not isinstance(cleanup, dict) or set(cleanup) != {"service", "remove_contents_only", "fail_closed"} or cleanup["remove_contents_only"] is not True or cleanup["fail_closed"] is not True:
        raise KioskFilesystemError("Política de neteja invàlida")
    files = raw["files"]
    if not isinstance(files, dict) or set(files) != {"tmpfiles", "home_mount", "cleanup_script", "cleanup_service", "environment", "policy"}:
        raise KioskFilesystemError("Destinacions de fitxers invàlides")
    for name, value in files.items():
        _safe_absolute(value, name)
    return raw


@dataclass(frozen=True, slots=True)
class KioskFilesystemPlan:
    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]
    enable_units: tuple[str, ...]

    def to_manifest(self) -> dict[str, object]:
        return {"files": [str(path) for path, _, _ in self.files], "enable_units": list(self.enable_units), "ephemeral_home": True, "enforcement": "enforce"}


def create_kiosk_filesystem_plan(rootfs: Path, profile_path: Path) -> KioskFilesystemPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise KioskFilesystemError(f"Rootfs insegur: {root}")
    profile = load_kiosk_filesystem_profile(profile_path)
    home, runtime, permissions, downloads = profile["home"], profile["runtime"], profile["permissions"], profile["downloads"]
    dirs = profile["allowed_directories"]
    tmpfiles = [f"d {item['path']} {item['mode'][1:]} xaac-kiosk xaac-kiosk -" for item in dirs]
    tmpfiles.append(f"d {runtime['path']} {runtime['mode'][1:]} xaac-kiosk xaac-kiosk -")
    mount = (
        "[Unit]\nDescription=XAAC ephemeral kiosk home\nBefore=xaac-kiosk-session.target\n\n"
        f"[Mount]\nWhat=tmpfs\nWhere={home['path']}\nType=tmpfs\nOptions=mode={home['mode'][1:]},uid=xaac-kiosk,gid=xaac-kiosk,size={home['size']},nr_inodes={home['inodes']},nosuid,nodev,noexec\n\n[Install]\nWantedBy=local-fs.target\n"
    )
    cleanup_script = (
        "#!/bin/sh\nset -eu\nTARGET=/home/xaac-kiosk\n"
        "[ -d \"$TARGET\" ] || exit 0\n"
        "find \"$TARGET\" -mindepth 1 -xdev -delete\n"
    )
    cleanup_service = (
        "[Unit]\nDescription=Clean XAAC kiosk ephemeral state\nAfter=home-xaac\\x2dkiosk.mount\nBefore=xaac-kiosk-session.target\n\n"
        "[Service]\nType=oneshot\nExecStart=/usr/local/libexec/xaac/kiosk-cleanup\nUser=root\nGroup=root\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectSystem=strict\nReadWritePaths=/home/xaac-kiosk\n\n"
        "[Install]\nWantedBy=xaac-kiosk-session.target\n"
    )
    environment = f"HOME={home['path']}\nXDG_DOWNLOAD_DIR={downloads['path']}\nUMASK={permissions['umask']}\n"
    effective = {key: value for key, value in profile.items() if key != "files"}
    destinations = profile["files"]
    files = (
        (_safe_absolute(destinations["tmpfiles"], "tmpfiles"), "\n".join(tmpfiles) + "\n", 0o644),
        (_safe_absolute(destinations["home_mount"], "home_mount"), mount, 0o644),
        (_safe_absolute(destinations["cleanup_script"], "cleanup_script"), cleanup_script, 0o755),
        (_safe_absolute(destinations["cleanup_service"], "cleanup_service"), cleanup_service, 0o644),
        (_safe_absolute(destinations["environment"], "environment"), environment, 0o640),
        (_safe_absolute(destinations["policy"], "policy"), json.dumps(effective, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640),
    )
    return KioskFilesystemPlan(root, files, ("home-xaac\\x2dkiosk.mount", "xaac-kiosk-cleanup.service"))


class KioskFilesystemConfigurator:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise KioskFilesystemError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        temporary.replace(path)

    def execute(self, plan: KioskFilesystemPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for relative, content, mode in plan.files:
            target = plan.rootfs / str(relative).lstrip("/")
            self._write(target, content, mode)
            written.append(target)
        for unit in plan.enable_units:
            wants = "local-fs.target.wants" if unit.endswith(".mount") else "xaac-kiosk-session.target.wants"
            link = plan.rootfs / "etc/systemd/system" / wants / unit
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.exists() or link.is_symlink():
                if link.is_symlink() and link.readlink() == PurePosixPath("../" + unit):
                    written.append(link)
                    continue
                link.unlink()
            link.symlink_to("../" + unit)
            written.append(link)
        return tuple(written)
