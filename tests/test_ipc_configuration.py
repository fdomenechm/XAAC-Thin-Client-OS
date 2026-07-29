from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from xaac_thin_client_os.cli import build_parser
from xaac_thin_client_os.ipc_configuration import (
    IpcConfigurationError,
    IpcConfigurator,
    IpcEnvelope,
    load_ipc_profile,
)


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "ipc.yaml"
    path.write_text(Path("config/ipc.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_profile_selects_authenticated_unix_socket() -> None:
    profile = load_ipc_profile(Path("config/ipc.yaml"))
    assert profile["transport"]["type"] == "unix_socket"
    assert profile["security"]["require_peer_credentials"] is True
    assert profile["protocol"]["version"] == 1


def test_profile_rejects_dbus_transport(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/ipc.yaml").read_text())
    data["transport"]["type"] = "dbus"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(IpcConfigurationError, match="unix_socket"):
        load_ipc_profile(path)


def test_profile_rejects_socket_outside_runtime_directory(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/ipc.yaml").read_text())
    data["transport"]["path"] = "/tmp/agent.sock"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(IpcConfigurationError, match="/run/xaac"):
        load_ipc_profile(path)


def test_profile_rejects_world_accessible_socket(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/ipc.yaml").read_text())
    data["transport"]["socket_mode"] = "0666"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(IpcConfigurationError, match="massa permissiu"):
        load_ipc_profile(path)


def test_envelope_round_trip() -> None:
    profile = load_ipc_profile(Path("config/ipc.yaml"))
    original = IpcEnvelope("ping", "request-1", 1, {"client": "xaac"})
    decoded = IpcEnvelope.decode(original.encode(profile), profile)
    assert decoded == original


def test_envelope_rejects_unknown_message() -> None:
    profile = load_ipc_profile(Path("config/ipc.yaml"))
    with pytest.raises(IpcConfigurationError, match="no autoritzat"):
        IpcEnvelope("shell", "request-2", 1, {}).encode(profile)


def test_envelope_rejects_oversized_payload(tmp_path: Path) -> None:
    profile = load_ipc_profile(_profile(tmp_path))
    profile["protocol"]["maximum_message_bytes"] = 64
    with pytest.raises(IpcConfigurationError, match="massa gran"):
        IpcEnvelope("ping", "request-3", 1, {"data": "x" * 100}).encode(profile)


def test_installer_dry_run_does_not_write(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    root.mkdir()
    paths = IpcConfigurator().install(root, _profile(tmp_path), dry_run=True)
    assert len(paths) == 3
    assert not (root / "etc/xaac/ipc.yaml").exists()


def test_installer_writes_configuration_tmpfiles_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    root.mkdir()
    paths = IpcConfigurator().install(root, _profile(tmp_path))
    assert all(path.is_file() for path in paths)
    tmpfiles = (root / "usr/lib/tmpfiles.d/xaac-ipc.conf").read_text()
    assert "d /run/xaac 0750 xaac-agent xaac-ipc" in tmpfiles
    manifest = json.loads((root / "etc/xaac/ipc-manifest.json").read_text())
    assert manifest["authentication"] == "SO_PEERCRED"
    assert manifest["protocol_version"] == 1


def test_installer_rejects_symlink_destination(tmp_path: Path) -> None:
    root = tmp_path / "rootfs"
    (root / "etc/xaac").mkdir(parents=True)
    (root / "etc/xaac/ipc.yaml").symlink_to("/tmp/unsafe")
    with pytest.raises(IpcConfigurationError, match="enllaç simbòlic"):
        IpcConfigurator().install(root, _profile(tmp_path))


def test_cli_exposes_ipc_command() -> None:
    args = build_parser().parse_args(["configure-ipc", "--dry-run"])
    assert args.command == "configure-ipc"
    assert args.dry_run is True
