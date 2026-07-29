"""Safe deterministic GPT partition planning for the XAAC image."""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import yaml


class PartitioningError(RuntimeError):
    """Raised when partition configuration or execution is unsafe."""


_TOKEN = re.compile(r"^[A-Z0-9_]{1,16}$")
_TYPE = re.compile(r"^[0-9A-Fa-f]{4}$")


@dataclass(frozen=True, slots=True)
class PartitionSpec:
    name: str
    number: int
    size_mib: int
    type_code: str
    filesystem: str
    label: str
    mountpoint: PurePosixPath
    options: str


@dataclass(frozen=True, slots=True)
class PartitionPlan:
    rootfs: Path
    device: Path
    disk_size_mib: int
    alignment_mib: int
    partitions: tuple[PartitionSpec, ...]

    @property
    def fstab_path(self) -> Path:
        return self.rootfs / "etc/fstab"

    def partition_path(self, number: int) -> Path:
        suffix = f"p{number}" if self.device.name[-1:].isdigit() else str(number)
        return self.device.with_name(self.device.name + suffix)

    @property
    def commands(self) -> tuple[tuple[str, ...], ...]:
        commands: list[tuple[str, ...]] = [("sgdisk", "--zap-all", str(self.device))]
        start = self.alignment_mib
        for item in self.partitions:
            end = start + item.size_mib
            commands.append(("sgdisk", f"--new={item.number}:{start}MiB:{end}MiB", f"--typecode={item.number}:{item.type_code}", f"--change-name={item.number}:{item.label}", str(self.device)))
            start = end
        commands.append(("partprobe", str(self.device)))
        for item in self.partitions:
            target = str(self.partition_path(item.number))
            if item.filesystem == "vfat":
                commands.append(("mkfs.vfat", "-F", "32", "-n", item.label, target))
            else:
                commands.append(("mkfs.ext4", "-F", "-L", item.label, target))
        return tuple(commands)

    def fstab_content(self) -> str:
        lines = ["# XAAC Thin Client OS - generated partition table"]
        for item in self.partitions:
            fs = "vfat" if item.filesystem == "vfat" else "ext4"
            passno = 1 if item.mountpoint == PurePosixPath("/") else 2
            lines.append(f"LABEL={item.label}\t{item.mountpoint}\t{fs}\t{item.options}\t0\t{passno}")
        return "\n".join(lines) + "\n"

    def to_manifest(self) -> dict[str, object]:
        return {"device": str(self.device), "disk_size_mib": self.disk_size_mib, "alignment_mib": self.alignment_mib, "partitions": [{"name": p.name, "number": p.number, "size_mib": p.size_mib, "type_code": p.type_code, "filesystem": p.filesystem, "label": p.label, "mountpoint": str(p.mountpoint), "options": p.options} for p in self.partitions], "commands": [list(c) for c in self.commands]}


@dataclass(frozen=True, slots=True)
class PartitionResult:
    plan: PartitionPlan
    log_path: Path
    executed: bool
    files_written: tuple[Path, ...]
    commands_executed: int


def _load(path: Path) -> dict[str, object]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PartitioningError(f"No es pot llegir {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PartitioningError("La configuració de particions ha de ser un mapa YAML")
    allowed = {"schema", "disk_size_mib", "alignment_mib", "partitions"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise PartitioningError("Claus desconegudes: " + ", ".join(unknown))
    return payload


def create_partition_plan(rootfs: Path, config_path: Path, device: Path) -> PartitionPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.parent == Path("/"):
        raise PartitioningError(f"Rootfs insegur: {root}")
    if not device.is_absolute() or not str(device).startswith("/dev/") or ".." in device.parts:
        raise PartitioningError("El dispositiu ha de ser una ruta segura sota /dev")
    payload = _load(config_path)
    if payload.get("schema") != "gpt":
        raise PartitioningError("schema ha de ser gpt")
    disk_size = payload.get("disk_size_mib")
    alignment = payload.get("alignment_mib")
    if not isinstance(disk_size, int) or isinstance(disk_size, bool) or disk_size < 4096:
        raise PartitioningError("disk_size_mib ha de ser un enter d'almenys 4096")
    if not isinstance(alignment, int) or isinstance(alignment, bool) or alignment not in range(1, 17):
        raise PartitioningError("alignment_mib ha d'estar entre 1 i 16")
    raw = payload.get("partitions")
    if not isinstance(raw, list) or len(raw) != 4:
        raise PartitioningError("Calen exactament quatre particions")
    specs: list[PartitionSpec] = []
    numbers: set[int] = set(); labels: set[str] = set(); mounts: set[PurePosixPath] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise PartitioningError("Cada partició ha de ser un mapa")
        required = {"name", "number", "size_mib", "type_code", "filesystem", "label", "mountpoint", "options"}
        if set(item) != required:
            raise PartitioningError("Camps de partició incomplets o desconeguts")
        number = item["number"]; size = item["size_mib"]
        if not isinstance(number, int) or number < 1 or number > 128 or number in numbers:
            raise PartitioningError("Número de partició no vàlid o duplicat")
        if not isinstance(size, int) or size < 64:
            raise PartitioningError("La mida de partició ha de ser almenys 64 MiB")
        label = item["label"]
        if not isinstance(label, str) or not _TOKEN.fullmatch(label) or label in labels:
            raise PartitioningError("Etiqueta no vàlida o duplicada")
        type_code = item["type_code"]
        if not isinstance(type_code, str) or not _TYPE.fullmatch(type_code):
            raise PartitioningError("type_code no és vàlid")
        fs = item["filesystem"]
        if fs not in {"vfat", "ext4"}:
            raise PartitioningError("filesystem ha de ser vfat o ext4")
        mount = PurePosixPath(str(item["mountpoint"]))
        if not mount.is_absolute() or ".." in mount.parts or mount in mounts:
            raise PartitioningError("Punt de muntatge insegur o duplicat")
        options = item["options"]
        if not isinstance(options, str) or not options or any(c.isspace() for c in options):
            raise PartitioningError("Opcions de muntatge no vàlides")
        specs.append(PartitionSpec(str(item["name"]), number, size, type_code.upper(), fs, label, mount, options))
        numbers.add(number); labels.add(label); mounts.add(mount)
    specs.sort(key=lambda p: p.number)
    if sum(p.size_mib for p in specs) + alignment > disk_size:
        raise PartitioningError("Les particions excedeixen la mida del disc")
    expected = {"XAAC_EFI", "XAAC_ROOT", "XAAC_DATA", "XAAC_RECOVERY"}
    if labels != expected or specs[0].filesystem != "vfat" or PurePosixPath("/") not in mounts:
        raise PartitioningError("L'esquema ha d'incloure EFI, arrel, dades i recuperació")
    return PartitionPlan(root, device, disk_size, alignment, tuple(specs))


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class PartitionConfigurator:
    def __init__(self, *, geteuid: Callable[[], int] = os.geteuid, runner: CommandRunner = subprocess.run) -> None:
        self._geteuid = geteuid; self._runner = runner

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise PartitioningError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8"); tmp.chmod(0o644); tmp.replace(path)

    def execute(self, plan: PartitionPlan, log_path: Path, *, dry_run: bool = False, confirm_destructive: bool = False) -> PartitionResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if dry_run:
            log_path.write_text("DRY-RUN\n" + "\n".join(" ".join(c) for c in plan.commands) + f"\nwrite {plan.fstab_path}\n", encoding="utf-8")
            return PartitionResult(plan, log_path, False, (), 0)
        if not confirm_destructive:
            raise PartitioningError("Cal --confirm-destructive per modificar el disc")
        if self._geteuid() != 0:
            raise PartitioningError("El particionament requereix privilegis de root")
        if not plan.device.exists() or not plan.device.is_block_device():
            raise PartitioningError(f"El dispositiu no existeix o no és de bloc: {plan.device}")
        with log_path.open("w", encoding="utf-8") as log:
            for command in plan.commands:
                log.write(f"$ {' '.join(command)}\n"); log.flush()
                try:
                    self._runner(command, check=True, stdout=log, stderr=subprocess.STDOUT, text=True)
                except subprocess.CalledProcessError as exc:
                    raise PartitioningError(f"Ha fallat {command[0]} amb codi {exc.returncode}; consulteu {log_path}") from exc
                except OSError as exc:
                    raise PartitioningError(f"No s'ha pogut executar {command[0]}: {exc}") from exc
        self._write_atomic(plan.fstab_path, plan.fstab_content())
        return PartitionResult(plan, log_path, True, (plan.fstab_path,), len(plan.commands))
