import json
from pathlib import Path

import pytest

from xaac_thin_client_os.kiosk_filesystem import (
    KioskFilesystemConfigurator,
    KioskFilesystemError,
    create_kiosk_filesystem_plan,
    load_kiosk_filesystem_profile,
)


def test_profile_covers_phase_5_5_controls(project_root: Path) -> None:
    profile = load_kiosk_filesystem_profile(project_root / "config/kiosk-filesystem.yaml")
    assert profile["policy"]["default_decision"] == "deny"
    assert profile["home"]["ephemeral"] is True
    assert profile["home"]["backing"] == "tmpfs"
    assert profile["downloads"]["executable_files"] is False
    assert profile["downloads"]["clear_on_session_end"] is True
    assert profile["permissions"]["umask"] == "0077"


def test_plan_generates_mount_tmpfiles_cleanup_and_policy(tmp_path: Path, project_root: Path) -> None:
    plan = create_kiosk_filesystem_plan(tmp_path / "build/rootfs", project_root / "config/kiosk-filesystem.yaml")
    contents = {str(path): (content, mode) for path, content, mode in plan.files}
    mount = contents["/etc/systemd/system/home-xaac\\x2dkiosk.mount"][0]
    assert "Type=tmpfs" in mount
    assert "nosuid,nodev,noexec" in mount
    assert "size=192M" in mount
    tmpfiles = contents["/usr/lib/tmpfiles.d/xaac-kiosk-filesystem.conf"][0]
    assert "/home/xaac-kiosk/Downloads" in tmpfiles
    script, mode = contents["/usr/local/libexec/xaac/kiosk-cleanup"]
    assert "find \"$TARGET\" -mindepth 1 -xdev -delete" in script
    assert mode == 0o755
    policy = json.loads(contents["/etc/xaac/kiosk/filesystem-policy.json"][0])
    assert policy["cleanup"]["fail_closed"] is True


def test_execute_is_idempotent_and_enables_units(tmp_path: Path, project_root: Path) -> None:
    plan = create_kiosk_filesystem_plan(tmp_path / "build/rootfs", project_root / "config/kiosk-filesystem.yaml")
    configurator = KioskFilesystemConfigurator()
    assert configurator.execute(plan, dry_run=True) == ()
    first = configurator.execute(plan)
    second = configurator.execute(plan)
    assert first == second
    mount_link = plan.rootfs / "etc/systemd/system/local-fs.target.wants/home-xaac\\x2dkiosk.mount"
    cleanup_link = plan.rootfs / "etc/systemd/system/xaac-kiosk-session.target.wants/xaac-kiosk-cleanup.service"
    assert mount_link.is_symlink()
    assert cleanup_link.is_symlink()
    assert (plan.rootfs / "usr/local/libexec/xaac/kiosk-cleanup").stat().st_mode & 0o777 == 0o755
    assert not list(plan.rootfs.rglob("*.tmp"))


def test_unsafe_root_and_symlink_are_rejected(tmp_path: Path, project_root: Path) -> None:
    profile = project_root / "config/kiosk-filesystem.yaml"
    with pytest.raises(KioskFilesystemError, match="Rootfs insegur"):
        create_kiosk_filesystem_plan(Path("/"), profile)
    plan = create_kiosk_filesystem_plan(tmp_path / "build/rootfs", profile)
    target = plan.rootfs / "etc/xaac/kiosk/filesystem-policy.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(KioskFilesystemError, match="enllaç simbòlic"):
        KioskFilesystemConfigurator().execute(plan)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("default_decision: deny", "default_decision: allow", "denegar"),
        ("ephemeral: true", "ephemeral: false", "efímer"),
        ("backing: tmpfs", "backing: disk", "efímer"),
        ("clear_on_stop: true", "clear_on_stop: false", "netejar-se"),
        ("size: 192M", "size: unlimited", "Límits"),
        ("executable_files: false", "executable_files: true", "descàrregues"),
        ("umask: '0077'", "umask: '0022'", "permisos"),
        ("follow_symlinks: false", "follow_symlinks: true", "permisos"),
        ("policy: /etc/xaac/kiosk/filesystem-policy.json", "policy: ../outside", "Ruta insegura"),
    ],
)
def test_invalid_profiles_are_rejected(tmp_path: Path, project_root: Path, old: str, new: str, message: str) -> None:
    source = (project_root / "config/kiosk-filesystem.yaml").read_text(encoding="utf-8")
    assert old in source
    path = tmp_path / "filesystem.yaml"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(KioskFilesystemError, match=message):
        load_kiosk_filesystem_profile(path)


def test_cli_exposes_kiosk_filesystem_command() -> None:
    from xaac_thin_client_os.cli import build_parser

    args = build_parser().parse_args(["configure-kiosk-filesystem", "--dry-run"])
    assert args.command == "configure-kiosk-filesystem"
    assert args.dry_run
