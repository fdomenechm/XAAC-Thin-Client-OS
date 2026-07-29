import json
from pathlib import Path

import pytest

from xaac_thin_client_os.cli import build_parser, main


def test_parser_program_name() -> None:
    assert build_parser().prog == "xaac-os"


def test_version_command(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["version"]) == 0
    output = capsys.readouterr().out
    assert "XAAC Thin Client OS 0.1.0" in output


def test_check_python_command(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["check-python"]) == 0
    assert capsys.readouterr().out.strip() == "Python 3.13 compatible"


def test_no_command_shows_help(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([]) == 0
    assert "usage: xaac-os" in capsys.readouterr().out


def test_unsupported_runtime_exits(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def reject() -> None:
        from xaac_thin_client_os.runtime import UnsupportedPythonError

        raise UnsupportedPythonError("versió no compatible")

    monkeypatch.setattr("xaac_thin_client_os.cli.ensure_supported_python", reject)
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        main(["version"])
    assert exc_info.value.code == 2


def test_validate_command(project_root, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--root", str(project_root), "validate"]) == 0
    assert capsys.readouterr().out.strip() == "Configuració vàlida"


def test_inspect_command(project_root, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--root", str(project_root), "inspect"]) == 0
    output = capsys.readouterr().out
    assert "Perfil: wyse3040" in output
    assert "Paquets efectius:" in output


def test_json_version(capsys) -> None:  # type: ignore[no-untyped-def]
    import json

    assert main(["--json", "version"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["version"] == "0.1.0"


def test_clean_requires_force(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    build_dir = tmp_path / ".build"
    build_dir.mkdir()
    (build_dir / "artifact").write_text("x", encoding="utf-8")
    assert main(["--root", str(tmp_path), "clean"]) == 3
    assert build_dir.exists()
    assert "--force" in capsys.readouterr().out
    assert main(["--root", str(tmp_path), "clean", "--force"]) == 0
    assert not build_dir.exists()


def test_validate_invalid_root_returns_error(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        main(["--root", str(tmp_path), "validate"])
    assert exc_info.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_prepare_creates_workspace(project_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(project_root), "prepare"]) == 0
    output = capsys.readouterr().out
    assert "Espai de treball preparat" in output
    assert (project_root / ".build" / "current").is_file()
    current = (project_root / ".build" / "current").read_text(encoding="utf-8").strip()
    release = (
        project_root / ".build" / "runs" / current / "rendered" / "etc" / "xaac" / "os-release"
    )
    assert release.is_file()
    assert f'XAAC_OS_BUILD_ID="{current}"' in release.read_text(encoding="utf-8")


def test_prepare_json_returns_build_metadata(
    project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(project_root), "--json", "prepare"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["build_id"]
    assert payload["manifest"].endswith("manifest.json")
    assert len(payload["rendered_templates"]) == 2


def test_prepare_writes_verifiable_complete_manifest(project_root: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from xaac_thin_client_os.manifest import verify_manifest

    assert main(["--root", str(project_root), "prepare"]) == 0
    capsys.readouterr()
    current = (project_root / ".build" / "current").read_text(encoding="utf-8").strip()
    path = project_root / ".build" / "runs" / current / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert verify_manifest(path)
    assert payload["build_id"] == current
    assert payload["outputs"]["rendered_files"]
    assert payload["integrity"]["algorithm"] == "sha256"


def test_bootstrap_dry_run_creates_auditable_plan(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "xaac_thin_client_os.bootstrap.find_debootstrap",
        lambda: Path("/usr/sbin/debootstrap"),
    )
    assert main(["--root", str(project_root), "--json", "bootstrap", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["executed"] is False
    assert "--variant=minbase" in payload["command"]
    manifest = project_root / ".build" / "runs" / payload["build_id"] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"] == "bootstrap-planned"
    assert data["bootstrap"]["suite"] == "trixie"


def test_configure_apt_dry_run_updates_current_manifest(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "xaac_thin_client_os.bootstrap.find_debootstrap",
        lambda: Path("/usr/sbin/debootstrap"),
    )
    assert main(["--root", str(project_root), "bootstrap", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["--root", str(project_root), "--json", "configure-apt", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["executed"] is False
    manifest = project_root / ".build" / "runs" / payload["build_id"] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"] == "apt-planned"
    assert data["apt"]["format"] == "deb822"


def test_configure_apt_requires_current_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = Path(__file__).resolve().parents[1]
    for name in ("config", "profiles", "templates", "hooks"):
        import shutil

        shutil.copytree(source / name, tmp_path / name)
    for name in ("VERSION", "pyproject.toml"):
        (tmp_path / name).write_bytes((source / name).read_bytes())
    with pytest.raises(SystemExit) as exc_info:
        main(["--root", str(tmp_path), "configure-apt", "--dry-run"])
    assert exc_info.value.code == 2
    assert "executeu primer bootstrap" in capsys.readouterr().err


def test_configure_users_dry_run_updates_current_manifest(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "xaac_thin_client_os.bootstrap.find_debootstrap",
        lambda: Path("/usr/sbin/debootstrap"),
    )
    assert main(["--root", str(project_root), "bootstrap", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["--root", str(project_root), "--json", "configure-users", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["executed"] is False
    assert payload["users"] == ["xaac-admin", "xaac-kiosk"]
    manifest = project_root / ".build" / "runs" / payload["build_id"] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"] == "user-configuration-planned"
    assert data["user_configuration"]["users"][0]["locked"] is True


def test_configure_ssh_dry_run_updates_current_manifest(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "xaac_thin_client_os.bootstrap.find_debootstrap",
        lambda: Path("/usr/sbin/debootstrap"),
    )
    assert main(["--root", str(project_root), "bootstrap", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["--root", str(project_root), "--json", "configure-ssh", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["executed"] is False
    assert payload["allow_users"] == ["xaac-admin"]
    manifest = project_root / ".build" / "runs" / payload["build_id"] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"] == "ssh-configuration-planned"
    assert data["ssh_configuration"]["authentication"]["password"] is False


def test_configure_firewall_dry_run_updates_current_manifest(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "xaac_thin_client_os.bootstrap.find_debootstrap",
        lambda: Path("/usr/sbin/debootstrap"),
    )
    assert main(["--root", str(project_root), "bootstrap", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["--root", str(project_root), "--json", "configure-firewall", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["executed"] is False
    assert payload["backend"] == "nftables"
    manifest = project_root / ".build" / "runs" / payload["build_id"] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"] == "firewall-configuration-planned"
    assert data["firewall_configuration"]["policy"]["input"] == "drop"


def test_configure_kernel_dry_run_updates_current_manifest(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "xaac_thin_client_os.bootstrap.find_debootstrap",
        lambda: Path("/usr/sbin/debootstrap"),
    )
    assert main(["--root", str(project_root), "bootstrap", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["--root", str(project_root), "--json", "configure-kernel", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["executed"] is False
    assert "mmc_block" in payload["modules"]
    manifest = project_root / ".build" / "runs" / payload["build_id"] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"] == "kernel-initramfs-planned"
    assert data["kernel_initramfs"]["compression"] == "zstd"


def test_configure_uefi_dry_run_updates_current_manifest(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "xaac_thin_client_os.bootstrap.find_debootstrap",
        lambda: Path("/usr/sbin/debootstrap"),
    )
    assert main(["--root", str(project_root), "bootstrap", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["--root", str(project_root), "--json", "configure-uefi", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["executed"] is False
    assert payload["target"] == "x86_64-efi"
    manifest = project_root / ".build" / "runs" / payload["build_id"] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"] == "uefi-planned"
    assert data["uefi_boot"]["removable_fallback"] is True


def test_configure_systemd_dry_run_updates_current_manifest(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("xaac_thin_client_os.bootstrap.find_debootstrap", lambda: Path("/usr/sbin/debootstrap"))
    assert main(["--root", str(project_root), "bootstrap", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["--root", str(project_root), "--json", "configure-systemd", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["executed"] is False
    assert payload["default_target"] == "multi-user.target"
    manifest = project_root / ".build" / "runs" / payload["build_id"] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"] == "systemd-planned"
    assert data["systemd_configuration"]["journald"]["system_max_use"] == "96M"


def test_configure_localization_dry_run_updates_current_manifest(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("xaac_thin_client_os.bootstrap.find_debootstrap", lambda: Path("/usr/sbin/debootstrap"))
    assert main(["--root", str(project_root), "bootstrap", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["--root", str(project_root), "--json", "configure-localization", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["executed"] is False
    assert payload["locale"] == "ca_ES.UTF-8"
    assert payload["keyboard_layout"] == "es"
    assert payload["keyboard_variant"] == "cat"
    manifest = project_root / ".build" / "runs" / payload["build_id"] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"] == "localization-planned"
    assert data["localization"]["console"]["charmap"] == "UTF-8"


def test_build_image_dry_run_updates_manifest(project_root: Path, tmp_path: Path, capsys) -> None:
    import shutil
    from xaac_thin_client_os.workspace import WorkspaceManager
    project_copy = tmp_path / "project"
    shutil.copytree(project_root, project_copy, ignore=shutil.ignore_patterns(".build", ".git", ".pytest_cache", "__pycache__", ".coverage"))
    manager = WorkspaceManager(project_copy)
    with manager:
        workspace = manager.prepare({"schema_version": 1})
    workspace.rootfs_dir.mkdir(parents=True)
    result = main(["--root", str(project_copy), "--json", "build-image", "--dry-run"])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["executed"] is False
    manifest = json.loads(workspace.manifest_path.read_text())
    assert manifest["status"] == "image-planned"
    assert manifest["bootable_image"]["size_mib"] == 7168


def test_inspect_hardware_command_is_available() -> None:
    parser = build_parser()
    args = parser.parse_args(["inspect-hardware"])
    assert args.command == "inspect-hardware"
    assert args.report is None


def test_inspect_hardware_accepts_report_path() -> None:
    parser = build_parser()
    args = parser.parse_args(["inspect-hardware", "--report", "hardware.json"])
    assert args.report == Path("hardware.json")


def test_parser_accepts_emmc_commands() -> None:
    parser = build_parser()
    inspect_args = parser.parse_args(["inspect-emmc", "--report", "emmc.json"])
    assert inspect_args.command == "inspect-emmc"
    assert inspect_args.report == Path("emmc.json")
    configure_args = parser.parse_args(["configure-emmc", "--dry-run"])
    assert configure_args.command == "configure-emmc"
    assert configure_args.dry_run is True
