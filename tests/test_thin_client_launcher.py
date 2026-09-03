from pathlib import Path
import pytest

from xaac_thin_client_os.thin_client_launcher import (
    ThinClientLauncherConfigurator, ThinClientLauncherError,
    create_thin_client_launcher_plan, load_thin_client_launcher_profile,
)


def test_profile_uses_packaged_executable_and_kiosk_user(project_root: Path) -> None:
    profile = load_thin_client_launcher_profile(project_root / "config/thin-client-launcher.yaml")
    assert profile["application"]["user"] == "xaac-kiosk"
    assert profile["application"]["executable"] == "/usr/bin/xaac-thinclient"
    assert profile["launch"]["prevent_duplicates"] is True


def test_plan_contains_runtime_dependencies(tmp_path: Path, project_root: Path) -> None:
    plan = create_thin_client_launcher_plan(tmp_path / "build/rootfs", project_root / "config/thin-client-launcher.yaml")
    assert {"python3", "gir1.2-gtk-4.0", "util-linux"} <= set(plan.packages)


def test_launcher_checks_dependencies_and_prevents_duplicates(tmp_path: Path, project_root: Path) -> None:
    plan = create_thin_client_launcher_plan(tmp_path / "build/rootfs", project_root / "config/thin-client-launcher.yaml")
    files = {str(path): (content, mode) for path, content, mode in plan.files}
    launcher, mode = files["/usr/local/libexec/xaac-thin-client-launch"]
    assert 'EXECUTABLE=/usr/bin/xaac-thinclient' in launcher
    assert "/usr/bin/flock -n" in launcher
    assert 'exec /usr/bin/flock -n "$LOCK" "$EXECUTABLE"' in launcher
    assert 'RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}' in launcher
    assert 'LOCK="$RUNTIME_DIR/$LOCK_NAME"' in launcher
    assert '/run/user/xaac-kiosk/xaac-thin-client.lock' not in launcher
    assert '[ -S "$socket" ]' in launcher
    assert "--config" not in launcher
    assert mode == 0o755


def test_environment_and_default_configuration(tmp_path: Path, project_root: Path) -> None:
    plan = create_thin_client_launcher_plan(tmp_path / "build/rootfs", project_root / "config/thin-client-launcher.yaml")
    files = {str(path): (content, mode) for path, content, mode in plan.files}
    env, _ = files["/etc/xaac/session/thin-client.env"]
    assert "PYTHONDONTWRITEBYTECODE=1" in env and "GDK_BACKEND=wayland,x11" in env
    assert "/etc/xaac/thin-client/config.yaml" not in files


def test_policy_declares_journald_logging(tmp_path: Path, project_root: Path) -> None:
    plan = create_thin_client_launcher_plan(tmp_path / "build/rootfs", project_root / "config/thin-client-launcher.yaml")
    policy = next(content for path, content, _ in plan.files if str(path).endswith("thin-client-launch-policy.json"))
    assert '"destination": "journald"' in policy
    assert '"identifier": "xaac-thinclient"' in policy


def test_execute_is_idempotent(tmp_path: Path, project_root: Path) -> None:
    plan = create_thin_client_launcher_plan(tmp_path / "build/rootfs", project_root / "config/thin-client-launcher.yaml")
    configurator = ThinClientLauncherConfigurator()
    assert configurator.execute(plan, dry_run=True) == ()
    first = configurator.execute(plan)
    before = tuple((p.read_text(), p.stat().st_mode & 0o777) for p in first)
    second = configurator.execute(plan)
    assert tuple((p.read_text(), p.stat().st_mode & 0o777) for p in second) == before


def test_unsafe_rootfs_and_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    with pytest.raises(ThinClientLauncherError, match="Rootfs insegur"):
        create_thin_client_launcher_plan(Path("/"), project_root / "config/thin-client-launcher.yaml")
    plan = create_thin_client_launcher_plan(tmp_path / "build/rootfs", project_root / "config/thin-client-launcher.yaml")
    target = plan.rootfs / "usr/local/libexec/xaac-thin-client-launch"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "other")
    with pytest.raises(ThinClientLauncherError, match="enllaç simbòlic"):
        ThinClientLauncherConfigurator().execute(plan)


@pytest.mark.parametrize("old,new", [
    ("user: xaac-kiosk", "user: root"),
    ("executable: /usr/bin/xaac-thinclient", "executable: ../xaac-thinclient"),
    ("prevent_duplicates: true", "prevent_duplicates: false"),
    ("backend: wayland", "backend: invalid"),
    ("    - gir1.2-gtk-4.0", "    - invalid-gtk"),
])
def test_invalid_profiles_are_rejected(tmp_path: Path, project_root: Path, old: str, new: str) -> None:
    content = (project_root / "config/thin-client-launcher.yaml").read_text().replace(old, new, 1)
    path = tmp_path / "launcher.yaml"
    path.write_text(content)
    with pytest.raises(ThinClientLauncherError):
        load_thin_client_launcher_profile(path)


def test_cli_exposes_launcher_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["configure-thin-client-launcher", "--dry-run"])
    assert args.command == "configure-thin-client-launcher" and args.dry_run
