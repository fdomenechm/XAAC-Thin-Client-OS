from pathlib import Path
import pytest

from xaac_thin_client_os.kiosk_user import (
    KioskUserConfigurator, KioskUserError, create_kiosk_user_plan, load_kiosk_user_profile,
)


def test_profile_defines_locked_noninteractive_kiosk(project_root: Path) -> None:
    profile = load_kiosk_user_profile(project_root / "config/kiosk-user.yaml")
    assert profile["user"]["name"] == "xaac-kiosk"
    assert profile["user"]["shell"] == "/usr/sbin/nologin"
    assert profile["user"]["locked"] is True
    assert set(profile["user"]["supplementary_groups"]) == {"audio", "video", "input", "render", "xaac-ipc"}


def test_plan_contains_account_commands_and_permissions(tmp_path: Path, project_root: Path) -> None:
    plan = create_kiosk_user_plan(tmp_path / "build/rootfs", project_root / "config/kiosk-user.yaml")
    text = "\n".join(" ".join(command) for command in plan.commands)
    assert "/usr/sbin/nologin" in text and "usermod --lock xaac-kiosk" in text
    assert any(str(path) == "/var/lib/xaac-kiosk/.config" and mode == 0o750 for path, mode in plan.directories)


def test_generated_environment_and_tmpfiles(tmp_path: Path, project_root: Path) -> None:
    plan = create_kiosk_user_plan(tmp_path / "build/rootfs", project_root / "config/kiosk-user.yaml")
    files = {str(path): (content, mode) for path, content, mode in plan.files}
    env, mode = files["/etc/xaac/session/kiosk-user.env"]
    assert "HOME=/var/lib/xaac-kiosk" in env
    assert "XDG_CACHE_HOME=/run/user/xaac-kiosk/cache" in env
    assert mode == 0o640
    assert "d /run/user/xaac-kiosk 0700" in files["/usr/lib/tmpfiles.d/xaac-kiosk.conf"][0]


def test_execute_is_idempotent(tmp_path: Path, project_root: Path) -> None:
    plan = create_kiosk_user_plan(tmp_path / "build/rootfs", project_root / "config/kiosk-user.yaml")
    cfg = KioskUserConfigurator()
    assert cfg.execute(plan, dry_run=True) == ()
    first = cfg.execute(plan)
    before = tuple((p.read_text(), p.stat().st_mode & 0o777) for p in first)
    second = cfg.execute(plan)
    assert tuple((p.read_text(), p.stat().st_mode & 0o777) for p in second) == before


def test_unsafe_rootfs_and_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    with pytest.raises(KioskUserError, match="Rootfs insegur"):
        create_kiosk_user_plan(Path("/"), project_root / "config/kiosk-user.yaml")
    plan = create_kiosk_user_plan(tmp_path / "build/rootfs", project_root / "config/kiosk-user.yaml")
    target = plan.rootfs / "etc/xaac/session/kiosk-user.env"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "other")
    with pytest.raises(KioskUserError, match="enllaç simbòlic"):
        KioskUserConfigurator().execute(plan)


@pytest.mark.parametrize("old,new", [
    ("name: xaac-kiosk", "name: root"),
    ("shell: /usr/sbin/nologin", "shell: /bin/bash"),
    ("locked: true", "locked: false"),
    ("home: /var/lib/xaac-kiosk", "home: /home/xaac-kiosk"),
    ("home_mode: '0750'", "home_mode: '0777'"),
    ("    - render", "    - sudo"),
    ("environment: /etc/xaac/session/kiosk-user.env", "environment: ../unsafe"),
])
def test_invalid_profiles_are_rejected(tmp_path: Path, project_root: Path, old: str, new: str) -> None:
    content = (project_root / "config/kiosk-user.yaml").read_text().replace(old, new, 1)
    path = tmp_path / "kiosk-user.yaml"
    path.write_text(content)
    with pytest.raises(KioskUserError):
        load_kiosk_user_profile(path)


def test_cli_exposes_kiosk_user_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["configure-kiosk-user", "--dry-run"])
    assert args.command == "configure-kiosk-user" and args.dry_run
