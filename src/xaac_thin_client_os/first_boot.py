"""Install and execute the idempotent XAAC first-boot service (phase 6.4)."""
from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from xaac_thin_client_os.device_identity import DeviceIdentityManager


class FirstBootError(RuntimeError):
    """Raised when first-boot configuration or execution fails."""


def _absolute(value: object, field: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.is_absolute() or ".." in path.parts:
        raise FirstBootError(f"Ruta insegura: {field}")
    return path


def _under(root: Path, value: object) -> Path:
    return root / _absolute(value, "path").relative_to("/")


def load_first_boot_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FirstBootError(f"No s'ha pogut carregar el perfil de primer inici: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "service", "hardware", "security"} or raw.get("schema_version") != 1:
        raise FirstBootError("Esquema de primer inici invàlid")
    service = raw["service"]
    service_keys = {"unit_path", "executable_path", "configuration_path", "state_path", "completed_marker", "identity_profile", "wanted_by"}
    if not isinstance(service, dict) or set(service) != service_keys:
        raise FirstBootError("Configuració del servei incompleta")
    for key in service_keys - {"wanted_by"}:
        _absolute(service[key], key)
    if service["wanted_by"] not in {"multi-user.target", "graphical.target"}:
        raise FirstBootError("Target systemd no autoritzat")
    hardware = raw["hardware"]
    if not isinstance(hardware, dict) or set(hardware) != {"product_name_paths", "accepted_products", "meminfo_path", "minimum_ram_mib", "emmc_globs"}:
        raise FirstBootError("Configuració de maquinari incompleta")
    if not hardware["product_name_paths"] or not hardware["accepted_products"] or not hardware["emmc_globs"]:
        raise FirstBootError("Regles de maquinari buides")
    for key in ("product_name_paths", "emmc_globs"):
        for value in hardware[key]:
            _absolute(value, key)
    _absolute(hardware["meminfo_path"], "meminfo_path")
    if not isinstance(hardware["minimum_ram_mib"], int) or hardware["minimum_ram_mib"] < 128:
        raise FirstBootError("Memòria mínima invàlida")
    security = raw["security"]
    if not isinstance(security, dict) or set(security) != {"directory_mode", "state_mode", "configuration_mode"}:
        raise FirstBootError("Política de seguretat incompleta")
    for key, value in security.items():
        try:
            mode = int(str(value), 8)
        except ValueError as exc:
            raise FirstBootError(f"Mode invàlid: {key}") from exc
        if mode & 0o002:
            raise FirstBootError(f"Mode massa permissiu: {key}")
    return raw


@dataclass(frozen=True, slots=True)
class HardwareValidation:
    product: str
    ram_mib: int
    emmc: str

    def to_dict(self) -> dict[str, object]:
        return {"product": self.product, "ram_mib": self.ram_mib, "emmc": self.emmc}


def validate_hardware(rootfs: Path, profile: dict[str, Any]) -> HardwareValidation:
    hardware = profile["hardware"]
    product = ""
    for value in hardware["product_name_paths"]:
        path = _under(rootfs, value)
        if path.is_file() and not path.is_symlink():
            product = path.read_text(encoding="utf-8", errors="replace").strip()
            if product:
                break
    if product not in hardware["accepted_products"]:
        raise FirstBootError(f"Maquinari no compatible: {product or 'desconegut'}")
    meminfo = _under(rootfs, hardware["meminfo_path"])
    try:
        line = next(line for line in meminfo.read_text(encoding="ascii").splitlines() if line.startswith("MemTotal:"))
        ram_mib = int(line.split()[1]) // 1024
    except (OSError, StopIteration, ValueError, IndexError) as exc:
        raise FirstBootError("No s'ha pogut validar la memòria RAM") from exc
    if ram_mib < hardware["minimum_ram_mib"]:
        raise FirstBootError(f"Memòria insuficient: {ram_mib} MiB")
    emmc_matches: list[str] = []
    for pattern in hardware["emmc_globs"]:
        host_pattern = str(_under(rootfs, pattern))
        emmc_matches.extend(glob.glob(host_pattern))
    safe_matches = sorted(path for path in emmc_matches if Path(path).exists() and not Path(path).is_symlink())
    if not safe_matches:
        raise FirstBootError("No s'ha detectat cap dispositiu eMMC")
    emmc = "/" + str(Path(safe_matches[0]).relative_to(rootfs))
    return HardwareValidation(product, ram_mib, emmc)


class FirstBootInstaller:
    """Install the configuration, executable and hardened systemd unit."""

    def install(self, rootfs: Path, profile_path: Path, *, dry_run: bool = False) -> tuple[Path, ...]:
        root = rootfs.resolve()
        if root == Path("/") or root.parent == Path("/"):
            raise FirstBootError(f"Rootfs insegur: {root}")
        profile = load_first_boot_profile(profile_path)
        service, security = profile["service"], profile["security"]
        paths = tuple(_under(root, service[key]) for key in ("unit_path", "executable_path", "configuration_path", "identity_profile"))
        for path in paths:
            if path.is_symlink():
                raise FirstBootError(f"No s'utilitzarà un enllaç simbòlic: {path}")
        if dry_run:
            return paths
        unit, executable, configuration, identity_configuration = paths
        for directory in {unit.parent, executable.parent, configuration.parent}:
            directory.mkdir(parents=True, exist_ok=True)
        configuration.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
        configuration.chmod(int(security["configuration_mode"], 8))
        source_identity = profile_path.parent / "device-identity.yaml"
        if not source_identity.is_file() or source_identity.is_symlink():
            raise FirstBootError("No existeix un perfil segur d’identitat del dispositiu")
        identity_configuration.write_text(source_identity.read_text(encoding="utf-8"), encoding="utf-8")
        identity_configuration.chmod(int(security["configuration_mode"], 8))
        executable.write_text("#!/bin/sh\nexec /usr/bin/python3 -m xaac_thin_client_os.first_boot --root / --profile /etc/xaac/first-boot.yaml\n", encoding="utf-8")
        executable.chmod(0o755)
        unit.write_text(self._unit(profile), encoding="utf-8")
        unit.chmod(0o644)
        wants = root / "etc/systemd/system" / f"{service['wanted_by']}.wants"
        wants.mkdir(parents=True, exist_ok=True)
        link = wants / unit.name
        if link.exists() or link.is_symlink():
            if not link.is_symlink() or link.readlink() != PurePosixPath("/usr/lib/systemd/system") / unit.name:
                raise FirstBootError(f"Enllaç systemd conflictiu: {link}")
        else:
            link.symlink_to(PurePosixPath("/usr/lib/systemd/system") / unit.name)
        return paths + (link,)

    @staticmethod
    def _unit(profile: dict[str, Any]) -> str:
        service = profile["service"]
        return f"""[Unit]\nDescription=XAAC device first-boot initialisation\nAfter=local-fs.target systemd-udev-settle.service\nBefore=xaac-agent.service greetd.service\nConditionPathExists=!{service['completed_marker']}\n\n[Service]\nType=oneshot\nExecStart={service['executable_path']}\nRemainAfterExit=yes\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectSystem=strict\nProtectHome=yes\nProtectKernelTunables=yes\nProtectKernelModules=yes\nProtectControlGroups=yes\nReadWritePaths=/etc/xaac /etc/hostname /etc/machine-id /var/lib/xaac-agent\n\n[Install]\nWantedBy={service['wanted_by']}\n"""


class FirstBootRunner:
    """Perform hardware validation and identity initialisation exactly once."""

    def run(self, rootfs: Path, profile_path: Path, *, identity_profile: Path | None = None, identity_manager: DeviceIdentityManager | None = None) -> dict[str, Any]:
        root = rootfs.resolve()
        profile = load_first_boot_profile(profile_path)
        service, security = profile["service"], profile["security"]
        state = _under(root, service["state_path"])
        completed = _under(root, service["completed_marker"])
        for path in (state, completed):
            if path.is_symlink():
                raise FirstBootError(f"No s'utilitzarà un enllaç simbòlic: {path}")
        if completed.exists():
            try:
                previous = json.loads(state.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise FirstBootError("Marcador complet sense estat vàlid") from exc
            if previous.get("status") != "completed":
                raise FirstBootError("Estat de primer inici inconsistent")
            return previous
        state.parent.mkdir(parents=True, exist_ok=True)
        state.parent.chmod(int(security["directory_mode"], 8))
        started = datetime.now(UTC).isoformat()
        try:
            hardware = validate_hardware(root, profile)
            manager = identity_manager or DeviceIdentityManager()
            selected_profile = identity_profile or _under(root, service["identity_profile"])
            identity = manager.create(root, selected_profile)
            payload: dict[str, Any] = {"schema_version": 1, "status": "completed", "started_at": started, "completed_at": datetime.now(UTC).isoformat(), "hardware": hardware.to_dict(), "identity_uuid": identity.uuid}
            self._write_state(state, payload, int(security["state_mode"], 8))
            completed.write_text(identity.uuid + "\n", encoding="ascii")
            completed.chmod(0o640)
            return payload
        except Exception as exc:
            payload = {"schema_version": 1, "status": "failed", "started_at": started, "failed_at": datetime.now(UTC).isoformat(), "error": str(exc)}
            self._write_state(state, payload, int(security["state_mode"], 8))
            if isinstance(exc, FirstBootError):
                raise
            raise FirstBootError(f"Ha fallat el primer inici: {exc}") from exc

    @staticmethod
    def _write_state(path: Path, payload: dict[str, Any], mode: int) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(mode)
        temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    FirstBootRunner().run(args.root, args.profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
