import json
import os
from pathlib import Path

import pytest

from xaac_thin_client_os.tty_control import (
    TtyControlConfigurator,
    TtyControlError,
    create_tty_control_plan,
    load_tty_control_profile,
)


def test_profile_covers_phase_5_4_controls(project_root: Path) -> None:
    profile = load_tty_control_profile(project_root / "config/tty-control.yaml")
    assert profile["policy"]["default_decision"] == "deny"
    assert profile["virtual_terminals"]["administrative_tty"] == 12
    assert profile["virtual_terminals"]["disabled_user_ttys"] == list(range(1, 12))
    assert profile["administration"]["allowed_user"] == "xaac-admin"
    assert profile["administration"]["authentication_required"] is True
    assert profile["switching"]["kiosk_switching_allowed"] is False
    assert profile["switching"]["reserved_shortcut"] == "Ctrl+Alt+F12"


def test_plan_generates_logind_getty_login_wrapper_and_masks(tmp_path: Path, project_root: Path) -> None:
    plan = create_tty_control_plan(tmp_path / "build/rootfs", project_root / "config/tty-control.yaml")
    contents = {str(path): (content, mode) for path, content, mode in plan.files}
    assert "NAutoVTs=0" in contents["/etc/systemd/logind.conf.d/30-xaac-tty-control.conf"][0]
    assert "ReserveVT=12" in contents["/etc/systemd/logind.conf.d/30-xaac-tty-control.conf"][0]
    override = contents["/etc/systemd/system/getty@tty12.service.d/30-xaac-admin.conf"][0]
    assert "tty-admin-login tty12 linux" in override
    wrapper, mode = contents["/usr/local/libexec/xaac/tty-admin-login"]
    assert "exec /bin/login xaac-admin" in wrapper
    assert mode == 0o755
    assert "getty@tty1.service" in plan.mask_units
    assert "autovt@tty11.service" in plan.mask_units
    assert "getty@tty12.service" not in plan.mask_units
    assert plan.enable_unit == "getty@tty12.service"
    policy = json.loads(contents["/etc/xaac/kiosk/tty-control.json"][0])
    assert policy["switching"]["require_capability"] == "CAP_SYS_TTY_CONFIG"


def test_execute_is_idempotent_and_creates_systemd_links(tmp_path: Path, project_root: Path) -> None:
    plan = create_tty_control_plan(tmp_path / "build/rootfs", project_root / "config/tty-control.yaml")
    configurator = TtyControlConfigurator()
    assert configurator.execute(plan, dry_run=True) == ()
    first = configurator.execute(plan)
    second = configurator.execute(plan)
    assert first == second
    mask = plan.rootfs / "etc/systemd/system/getty@tty1.service"
    assert mask.is_symlink() and os.readlink(mask) == "/dev/null"
    wants = plan.rootfs / "etc/systemd/system/getty.target.wants/getty@tty12.service"
    assert wants.is_symlink() and os.readlink(wants) == "/lib/systemd/system/getty@.service"
    wrapper = plan.rootfs / "usr/local/libexec/xaac/tty-admin-login"
    assert (wrapper.stat().st_mode & 0o777) == 0o755
    securetty = plan.rootfs / "etc/securetty.d/xaac-admin.conf"
    assert (securetty.stat().st_mode & 0o777) == 0o600
    assert not list(plan.rootfs.rglob("*.tmp"))


def test_unsafe_root_and_symlink_are_rejected(tmp_path: Path, project_root: Path) -> None:
    profile = project_root / "config/tty-control.yaml"
    with pytest.raises(TtyControlError, match="Rootfs insegur"):
        create_tty_control_plan(Path("/"), profile)
    plan = create_tty_control_plan(tmp_path / "build/rootfs", profile)
    target = plan.rootfs / "etc/xaac/kiosk/tty-control.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(TtyControlError, match="enllaç simbòlic"):
        TtyControlConfigurator().execute(plan)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("default_decision: deny", "default_decision: allow", "denegar"),
        ("administrative_tty: 12", "administrative_tty: 11", "administratiu"),
        ("disabled_user_ttys: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]", "disabled_user_ttys: [1, 2]", "Tots els TTY"),
        ("automatic_vts: 0", "automatic_vts: 6", "automàtics"),
        ("allowed_user: xaac-admin", "allowed_user: root", "xaac-admin"),
        ("authentication_required: true", "authentication_required: false", "autenticació"),
        ("kiosk_switching_allowed: false", "kiosk_switching_allowed: true", "bloquejat"),
        ("reserved_shortcut: Ctrl+Alt+F12", "reserved_shortcut: Ctrl+Alt+F11", "drecera"),
        ("policy: /etc/xaac/kiosk/tty-control.json", "policy: ../outside", "Ruta insegura"),
    ],
)
def test_invalid_profiles_are_rejected(tmp_path: Path, project_root: Path, old: str, new: str, message: str) -> None:
    source = (project_root / "config/tty-control.yaml").read_text(encoding="utf-8")
    assert old in source
    path = tmp_path / "tty.yaml"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(TtyControlError, match=message):
        load_tty_control_profile(path)


def test_cli_exposes_tty_control_command() -> None:
    from xaac_thin_client_os.cli import build_parser

    args = build_parser().parse_args(["configure-tty-control", "--dry-run"])
    assert args.command == "configure-tty-control"
    assert args.dry_run
