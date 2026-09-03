from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.device_identity import (
    DeviceIdentityError,
    DeviceIdentityManager,
    load_device_identity_profile,
)


def _profile(tmp_path: Path) -> Path:
    source = Path("config/device-identity.yaml")
    target = tmp_path / "identity.yaml"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _rootfs(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    (root / "sys/class/dmi/id").mkdir(parents=True)
    (root / "sys/class/dmi/id/product_serial").write_text("WYSE3040-ABC\n")
    (root / "sys/class/net/lo").mkdir(parents=True)
    (root / "sys/class/net/lo/address").write_text("00:00:00:00:00:00\n")
    (root / "sys/class/net/enp1s0").mkdir(parents=True)
    (root / "sys/class/net/enp1s0/address").write_text("00:11:22:33:44:55\n")
    return root


def _openssl(root: Path):
    def runner(command, **kwargs):
        args = list(command)
        Path(args[args.index("-keyout") + 1]).write_text("PRIVATE KEY\n")
        Path(args[args.index("-out") + 1]).write_text("CERTIFICATE\n")
        return subprocess.CompletedProcess(command, 0, "", "")
    return runner


def test_profile_is_valid() -> None:
    profile = load_device_identity_profile(Path("config/device-identity.yaml"))
    assert profile["identity"]["hostname_prefix"] == "xaac"
    assert profile["security"]["private_key_mode"] == "0600"


def test_profile_rejects_relative_state_path(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/device-identity.yaml").read_text())
    data["identity"]["state_path"] = "state.json"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(DeviceIdentityError, match="Ruta insegura"):
        load_device_identity_profile(path)


def test_profile_rejects_world_writable_key(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/device-identity.yaml").read_text())
    data["security"]["private_key_mode"] = "0602"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(DeviceIdentityError, match="massa permissiu"):
        load_device_identity_profile(path)


def test_dry_run_collects_identity_without_writes(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    identity = DeviceIdentityManager().create(root, _profile(tmp_path), dry_run=True)
    assert identity.serial == "WYSE3040-ABC"
    assert identity.mac == "00:11:22:33:44:55"
    assert identity.hostname.startswith("xaac-")
    assert not (root / "var/lib/xaac-agent/identity/device.json").exists()


def test_create_persists_identity_certificate_and_machine_id(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    identity = DeviceIdentityManager().create(root, _profile(tmp_path), runner=_openssl(root))
    state = root / "var/lib/xaac-agent/identity/device.json"
    assert json.loads(state.read_text())["uuid"] == identity.uuid
    assert (root / "etc/xaac/identity/device.crt").stat().st_mode & 0o777 == 0o644
    assert (root / "etc/xaac/identity/device.key").stat().st_mode & 0o777 == 0o600
    assert (root / "etc/hostname").read_text().strip() == identity.hostname
    assert (root / "etc/machine-id").read_text().strip() == identity.uuid.replace("-", "")


def test_existing_identity_is_idempotent(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    manager = DeviceIdentityManager()
    first = manager.create(root, _profile(tmp_path), runner=_openssl(root))
    second = manager.create(root, _profile(tmp_path), runner=lambda *a, **k: pytest.fail("openssl must not run"))
    assert second == first


def test_missing_serial_is_rejected(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    (root / "sys/class/dmi/id/product_serial").write_text("Unknown\n")
    with pytest.raises(DeviceIdentityError, match="número de sèrie"):
        DeviceIdentityManager().create(root, _profile(tmp_path), dry_run=True)


def test_multicast_mac_is_rejected(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    (root / "sys/class/net/enp1s0/address").write_text("01:11:22:33:44:55\n")
    with pytest.raises(DeviceIdentityError, match="MAC"):
        DeviceIdentityManager().create(root, _profile(tmp_path), dry_run=True)


def test_symlink_state_is_rejected(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    state = root / "var/lib/xaac-agent/identity/device.json"
    state.parent.mkdir(parents=True)
    state.symlink_to(tmp_path / "outside")
    with pytest.raises(DeviceIdentityError, match="enllaç simbòlic"):
        DeviceIdentityManager().create(root, _profile(tmp_path), dry_run=True)


def test_invalid_existing_identity_is_rejected(tmp_path: Path) -> None:
    root = _rootfs(tmp_path)
    state = root / "var/lib/xaac-agent/identity/device.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"uuid":"not-a-uuid"}')
    with pytest.raises(DeviceIdentityError, match="persistent invàlida"):
        DeviceIdentityManager().create(root, _profile(tmp_path), dry_run=True)
