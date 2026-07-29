from pathlib import Path
import pytest

from xaac_thin_client_os.session_manager import (
    SessionInventory, SessionManagerConfigurator, SessionManagerError,
    compare_session, create_session_manager_plan, load_session_manager_profile,
)


def valid_inventory(**changes: object) -> SessionInventory:
    values = dict(manager_running=True, active_user="xaac-kiosk", session_name="xaac-kiosk",
                  backend="wayland", autologin=True, interactive_greeter=False,
                  competing_managers=(), restart_count=0)
    values.update(changes)
    return SessionInventory(**values)  # type: ignore[arg-type]


def test_profile_selects_greetd_and_dedicated_user(project_root: Path) -> None:
    profile = load_session_manager_profile(project_root / "config/session-manager.yaml")
    assert profile["manager"]["name"] == "greetd"
    assert profile["session"]["user"] == "xaac-kiosk"
    assert profile["autologin"]["enabled"] is True


def test_valid_dedicated_session_is_compatible(project_root: Path) -> None:
    profile = load_session_manager_profile(project_root / "config/session-manager.yaml")
    assert compare_session(valid_inventory(), profile).compatible


@pytest.mark.parametrize("changes,failed", [
    ({"manager_running": False}, "manager"),
    ({"active_user": "root"}, "user"),
    ({"session_name": None}, "session"),
    ({"backend": "x11"}, "backend"),
    ({"autologin": False}, "autologin"),
    ({"interactive_greeter": True}, "greeter"),
    ({"competing_managers": ("gdm3",)}, "competing-managers"),
    ({"restart_count": 6}, "restart"),
])
def test_runtime_failures(project_root: Path, changes: dict[str, object], failed: str) -> None:
    report = compare_session(valid_inventory(**changes), load_session_manager_profile(project_root / "config/session-manager.yaml"))
    assert not report.compatible
    assert next(c for c in report.checks if c.name == failed).status == "fail"


def test_plan_generates_restricted_autologin(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_manager_plan(tmp_path / "build/rootfs", project_root / "config/session-manager.yaml")
    assert plan.packages == ("greetd",)
    assert {"gdm3", "lightdm", "sddm", "xdm"} <= set(plan.forbidden_packages)
    files = {p.as_posix(): (content, mode) for p, content, mode in plan.files}
    config, mode = files["/etc/greetd/config.toml"]
    assert 'user = "xaac-kiosk"' in config
    assert 'command = "/usr/local/libexec/xaac-session"' in config
    assert "vt = 1" in config
    assert mode == 0o600
    launcher, launcher_mode = files["/usr/local/libexec/xaac-session"]
    assert "exec /usr/bin/labwc" in launcher
    assert launcher_mode == 0o755


def test_execute_is_idempotent(tmp_path: Path, project_root: Path) -> None:
    plan = create_session_manager_plan(tmp_path / "build/rootfs", project_root / "config/session-manager.yaml")
    cfg = SessionManagerConfigurator()
    assert cfg.execute(plan, dry_run=True) == ()
    first = cfg.execute(plan)
    before = tuple((p.read_text(encoding="utf-8"), p.stat().st_mode & 0o777) for p in first)
    second = cfg.execute(plan)
    assert tuple((p.read_text(encoding="utf-8"), p.stat().st_mode & 0o777) for p in second) == before


def test_unsafe_rootfs_and_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    with pytest.raises(SessionManagerError, match="Rootfs insegur"):
        create_session_manager_plan(Path("/"), project_root / "config/session-manager.yaml")
    plan = create_session_manager_plan(tmp_path / "build/rootfs", project_root / "config/session-manager.yaml")
    target = plan.rootfs / "etc/greetd/config.toml"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "other")
    with pytest.raises(SessionManagerError, match="enllaç simbòlic"):
        SessionManagerConfigurator().execute(plan)


@pytest.mark.parametrize("old,new", [
    ("name: greetd", "name: gdm3"),
    ("user: xaac-kiosk", "user: root"),
    ("enabled: true", "enabled: false"),
    ("allow_other_sessions: false", "allow_other_sessions: true"),
    ("vt: 1", "vt: 0"),
    ("greetd_config: /etc/greetd/config.toml", "greetd_config: ../unsafe.toml"),
])
def test_invalid_profiles_are_rejected(tmp_path: Path, project_root: Path, old: str, new: str) -> None:
    content = (project_root / "config/session-manager.yaml").read_text(encoding="utf-8").replace(old, new, 1)
    path = tmp_path / "session-manager.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SessionManagerError):
        load_session_manager_profile(path)


def test_cli_exposes_session_manager_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["configure-session-manager", "--dry-run"])
    assert args.command == "configure-session-manager" and args.dry_run
