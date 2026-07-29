"""Declarative and safe RustDesk branding for phase 8.2."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class RustDeskBrandingError(RuntimeError):
    """Raised when the RustDesk branding profile is invalid or unsafe."""


_APP_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_-]+)+$")
_ICON = re.compile(r"^[a-z0-9][a-z0-9.-]+$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){2}(?:[+~.-][A-Za-z0-9.+~:-]+)?$")


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise RustDeskBrandingError(f"Ruta insegura: {field}")
    return path


def _relative_asset(value: object, field: str) -> Path:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".svg":
        raise RustDeskBrandingError(f"Recurs de branding insegur: {field}")
    return path


def load_rustdesk_branding_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RustDeskBrandingError(f"No s'ha pogut carregar el branding RustDesk: {exc}") from exc
    expected = {"schema_version", "identity", "assets", "texts", "servers", "version", "outputs"}
    if not isinstance(raw, dict) or set(raw) != expected or raw.get("schema_version") != 1:
        raise RustDeskBrandingError("Esquema de branding RustDesk invàlid")
    identity = raw["identity"]
    if not isinstance(identity, dict) or set(identity) != {"product_name", "application_id", "desktop_id", "icon_name", "vendor"}:
        raise RustDeskBrandingError("Identitat RustDesk incompleta")
    if not all(isinstance(identity[key], str) and identity[key].strip() for key in identity):
        raise RustDeskBrandingError("Identitat RustDesk buida")
    if not _APP_ID.fullmatch(identity["application_id"]) or not identity["desktop_id"].endswith(".desktop") or not _ICON.fullmatch(identity["icon_name"]):
        raise RustDeskBrandingError("Identificadors RustDesk invàlids")
    assets = raw["assets"]
    if not isinstance(assets, dict) or set(assets) != {"icon", "logo", "icon_target", "logo_target"}:
        raise RustDeskBrandingError("Recursos RustDesk incomplets")
    _relative_asset(assets["icon"], "icon")
    _relative_asset(assets["logo"], "logo")
    _absolute(assets["icon_target"], "icon_target")
    _absolute(assets["logo_target"], "logo_target")
    texts = raw["texts"]
    if not isinstance(texts, dict) or set(texts) != {"window_title", "about_title", "support_label", "privacy_notice"} or not all(isinstance(value, str) and value.strip() for value in texts.values()):
        raise RustDeskBrandingError("Textos RustDesk incomplets")
    servers = raw["servers"]
    if not isinstance(servers, dict) or set(servers) != {"id_label", "relay_label", "configuration_managed"} or servers["configuration_managed"] is not True:
        raise RustDeskBrandingError("Etiquetes de servidor RustDesk invàlides")
    version = raw["version"]
    if not isinstance(version, dict) or set(version) != {"product_version", "upstream_product", "upstream_version", "display"}:
        raise RustDeskBrandingError("Informació de versió RustDesk incompleta")
    if not _VERSION.fullmatch(str(version["product_version"])) or not _VERSION.fullmatch(str(version["upstream_version"])) or version["upstream_product"] != "RustDesk":
        raise RustDeskBrandingError("Informació de versió RustDesk invàlida")
    outputs = raw["outputs"]
    if not isinstance(outputs, dict) or set(outputs) != {"branding_manifest", "desktop_entry", "environment_file"}:
        raise RustDeskBrandingError("Eixides de branding RustDesk incompletes")
    for key, value in outputs.items():
        _absolute(value, key)
    return raw


@dataclass(frozen=True, slots=True)
class RustDeskBrandingPlan:
    rootfs: Path
    project_root: Path
    profile: dict[str, Any]

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "identity": self.profile["identity"],
            "texts": self.profile["texts"],
            "servers": self.profile["servers"],
            "version": self.profile["version"],
            "assets": {
                "icon": self.profile["assets"]["icon_target"],
                "logo": self.profile["assets"]["logo_target"],
            },
        }

    def target_paths(self) -> tuple[PurePosixPath, ...]:
        outputs = self.profile["outputs"]
        assets = self.profile["assets"]
        return tuple(_absolute(value, key) for key, value in (
            ("icon_target", assets["icon_target"]),
            ("logo_target", assets["logo_target"]),
            ("branding_manifest", outputs["branding_manifest"]),
            ("desktop_entry", outputs["desktop_entry"]),
            ("environment_file", outputs["environment_file"]),
        ))


def create_rustdesk_branding_plan(rootfs: Path, project_root: Path, profile_path: Path) -> RustDeskBrandingPlan:
    root = rootfs.resolve()
    project = project_root.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise RustDeskBrandingError(f"Rootfs insegur: {root}")
    profile = load_rustdesk_branding_profile(profile_path)
    for field in ("icon", "logo"):
        source = (project / _relative_asset(profile["assets"][field], field)).resolve()
        try:
            source.relative_to(project)
        except ValueError as exc:
            raise RustDeskBrandingError("El recurs queda fora del projecte") from exc
        if not source.is_file() or source.is_symlink():
            raise RustDeskBrandingError(f"No existeix un recurs regular: {source}")
    return RustDeskBrandingPlan(root, project, profile)


class RustDeskBrandingInstaller:
    @staticmethod
    def _target(rootfs: Path, path: PurePosixPath) -> Path:
        return rootfs / path.relative_to("/")

    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise RustDeskBrandingError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        temporary.replace(path)

    def install(self, plan: RustDeskBrandingPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        if dry_run:
            return ()
        profile = plan.profile
        assets = profile["assets"]
        written: list[Path] = []
        for source_key, target_key in (("icon", "icon_target"), ("logo", "logo_target")):
            source = plan.project_root / assets[source_key]
            target = self._target(plan.rootfs, _absolute(assets[target_key], target_key))
            if target.is_symlink():
                raise RustDeskBrandingError(f"No s'escriurà sobre un enllaç simbòlic: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".tmp")
            shutil.copyfile(source, temporary)
            temporary.chmod(0o644)
            temporary.replace(target)
            written.append(target)
        outputs = profile["outputs"]
        manifest = self._target(plan.rootfs, _absolute(outputs["branding_manifest"], "branding_manifest"))
        self._write(manifest, json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        written.append(manifest)
        identity = profile["identity"]
        texts = profile["texts"]
        desktop = self._target(plan.rootfs, _absolute(outputs["desktop_entry"], "desktop_entry"))
        desktop_content = "\n".join((
            "[Desktop Entry]", "Type=Application", f"Name={identity['product_name']}",
            f"Comment={texts['support_label']}", "Exec=rustdesk", f"Icon={identity['icon_name']}",
            "Terminal=false", "Categories=Network;RemoteAccess;", "StartupNotify=true", "",
        ))
        self._write(desktop, desktop_content, 0o644)
        written.append(desktop)
        environment = self._target(plan.rootfs, _absolute(outputs["environment_file"], "environment_file"))
        env_content = "\n".join((
            f"XAAC_RUSTDESK_PRODUCT_NAME={json.dumps(identity['product_name'], ensure_ascii=False)}",
            f"XAAC_RUSTDESK_WINDOW_TITLE={json.dumps(texts['window_title'], ensure_ascii=False)}",
            f"XAAC_RUSTDESK_LOGO={json.dumps(assets['logo_target'])}",
            f"XAAC_RUSTDESK_VERSION={json.dumps(profile['version']['display'], ensure_ascii=False)}", "",
        ))
        self._write(environment, env_content, 0o640)
        written.append(environment)
        return tuple(written)
