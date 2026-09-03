"""Local device control policy for kiosk phase 5.6."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class LocalDeviceControlError(RuntimeError):
    """Raised when the local-device policy is invalid or unsafe."""


_VID_PID = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$")


def _safe_absolute(value: object, name: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise LocalDeviceControlError(f"Ruta insegura: {name}")
    return path


def load_local_device_control_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LocalDeviceControlError(f"No s'ha pogut carregar la política de dispositius: {exc}") from exc
    required = {"schema_version", "policy", "usb", "storage", "cameras", "smartcards", "printers", "files"}
    if not isinstance(raw, dict) or set(raw) != required or raw.get("schema_version") != 1:
        raise LocalDeviceControlError("Esquema de dispositius locals invàlid")
    policy = raw["policy"]
    if not isinstance(policy, dict) or set(policy) != {"identifier", "default_decision", "enforcement_mode", "kiosk_user"}:
        raise LocalDeviceControlError("Política de dispositius incompleta")
    if policy["default_decision"] != "deny" or policy["enforcement_mode"] != "enforce" or policy["kiosk_user"] != "xaac-kiosk":
        raise LocalDeviceControlError("La política ha de denegar per defecte i aplicar-se a xaac-kiosk")
    usb = raw["usb"]
    expected_usb = {"default_action", "allow_hid", "allow_smartcard", "allow_printers", "allow_cameras", "allow_mass_storage", "authorized_vid_pid"}
    if not isinstance(usb, dict) or set(usb) != expected_usb or usb["default_action"] != "deny":
        raise LocalDeviceControlError("Política USB invàlida")
    if any(not isinstance(usb[k], bool) for k in expected_usb - {"default_action", "authorized_vid_pid"}):
        raise LocalDeviceControlError("Valors USB invàlids")
    if not isinstance(usb["authorized_vid_pid"], list) or any(not _VID_PID.fullmatch(str(v)) for v in usb["authorized_vid_pid"]):
        raise LocalDeviceControlError("Llista VID/PID invàlida")
    storage = raw["storage"]
    if not isinstance(storage, dict) or set(storage) != {"automount", "removable_mounts", "executable_content", "filesystem_allowlist"}:
        raise LocalDeviceControlError("Política d'emmagatzematge invàlida")
    if any(storage[k] is not False for k in ("automount", "removable_mounts", "executable_content")) or not isinstance(storage["filesystem_allowlist"], list):
        raise LocalDeviceControlError("L'emmagatzematge extraïble ha d'estar bloquejat")
    for section in ("cameras", "smartcards", "printers"):
        item = raw[section]
        expected = {"enabled", "access_group"} | ({"pcsc_service"} if section == "smartcards" else {"cups_service"} if section == "printers" else set())
        if not isinstance(item, dict) or set(item) != expected or not isinstance(item["enabled"], bool) or not isinstance(item["access_group"], str):
            raise LocalDeviceControlError(f"Política {section} invàlida")
    files = raw["files"]
    if not isinstance(files, dict) or set(files) != {"udev_rules", "udisks_policy", "policy"}:
        raise LocalDeviceControlError("Destinacions de fitxers invàlides")
    for key, value in files.items():
        _safe_absolute(value, key)
    return raw


@dataclass(frozen=True, slots=True)
class LocalDeviceControlPlan:
    rootfs: Path
    files: tuple[tuple[PurePosixPath, str, int], ...]

    def to_manifest(self) -> dict[str, object]:
        return {"files": [str(path) for path, _, _ in self.files], "default_decision": "deny", "enforcement": "enforce"}


def create_local_device_control_plan(rootfs: Path, profile_path: Path) -> LocalDeviceControlPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise LocalDeviceControlError(f"Rootfs insegur: {root}")
    profile = load_local_device_control_profile(profile_path)
    usb = profile["usb"]
    rules = ["# Managed by XAAC Thin Client OS", 'SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{authorized}="0"']
    class_rules = []
    if usb["allow_hid"]:
        class_rules.append("03")
    if usb["allow_printers"]:
        class_rules.append("07")
    if usb["allow_mass_storage"]:
        class_rules.append("08")
    if usb["allow_smartcard"]:
        class_rules.append("0b")
    if usb["allow_cameras"]:
        class_rules.append("0e")
    for code in class_rules:
        rules.append(f'SUBSYSTEM=="usb", ENV{{DEVTYPE}}=="usb_device", ATTR{{bDeviceClass}}=="{code}", ATTR{{authorized}}="1"')
    for value in sorted(str(v).lower() for v in usb["authorized_vid_pid"]):
        vendor, product = value.split(":")
        rules.append(f'SUBSYSTEM=="usb", ENV{{DEVTYPE}}=="usb_device", ATTR{{idVendor}}=="{vendor}", ATTR{{idProduct}}=="{product}", ATTR{{authorized}}="1"')
    polkit = '''polkit.addRule(function(action, subject) {\n  if (subject.user == "xaac-kiosk" && action.id.indexOf("org.freedesktop.udisks2.") == 0) {\n    return polkit.Result.NO;\n  }\n});\n'''
    effective = {key: value for key, value in profile.items() if key != "files"}
    files = profile["files"]
    return LocalDeviceControlPlan(root, (
        (_safe_absolute(files["udev_rules"], "udev_rules"), "\n".join(rules) + "\n", 0o644),
        (_safe_absolute(files["udisks_policy"], "udisks_policy"), polkit, 0o644),
        (_safe_absolute(files["policy"], "policy"), json.dumps(effective, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640),
    ))


class LocalDeviceControlConfigurator:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise LocalDeviceControlError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        temporary.replace(path)

    def execute(self, plan: LocalDeviceControlPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        written: list[Path] = []
        for relative, content, mode in plan.files:
            destination = plan.rootfs / relative.relative_to("/")
            self._write(destination, content, mode)
            written.append(destination)
        return tuple(written)
