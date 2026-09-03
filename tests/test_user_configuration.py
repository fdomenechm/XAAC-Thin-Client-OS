from pathlib import Path
import subprocess
import pytest

from xaac_thin_client_os.user_configuration import (
    UserConfigurationError, UserConfigurator, create_user_configuration_plan,
)


def _config(path: Path, *, locked: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'''schema_version: 1
groups:
  - name: xaac-admin
    system: true
users:
  - name: xaac-admin
    gecos: Administrator
    primary_group: xaac-admin
    supplementary_groups: [sudo]
    shell: /bin/bash
    home: /home/xaac-admin
    system: false
    locked: {str(locked).lower()}
''', encoding='utf-8')
    return path


def _plan(tmp_path: Path):
    return create_user_configuration_plan(tmp_path / 'runs/build/rootfs', _config(tmp_path / 'users.yaml'))


def test_plan_loads_users_and_commands(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert plan.groups[0].name == 'xaac-admin'
    assert plan.users[0].locked is True
    assert any('/usr/sbin/usermod' in command for command in plan.commands())


def test_plan_rejects_unsafe_rootfs(tmp_path: Path) -> None:
    with pytest.raises(UserConfigurationError, match='insegura'):
        create_user_configuration_plan(Path('/rootfs'), _config(tmp_path / 'users.yaml'))


def test_plan_rejects_unlocked_accounts(tmp_path: Path) -> None:
    with pytest.raises(UserConfigurationError, match='bloquejats'):
        create_user_configuration_plan(tmp_path / 'runs/build/rootfs', _config(tmp_path / 'users.yaml', locked=False))


def test_plan_rejects_missing_primary_group(tmp_path: Path) -> None:
    path = _config(tmp_path / 'users.yaml')
    path.write_text(path.read_text().replace('primary_group: xaac-admin', 'primary_group: missing'), encoding='utf-8')
    with pytest.raises(UserConfigurationError, match='no està declarat'):
        create_user_configuration_plan(tmp_path / 'runs/build/rootfs', path)


def test_dry_run_needs_no_root(tmp_path: Path) -> None:
    result = UserConfigurator(geteuid=lambda: 1000).execute(_plan(tmp_path), tmp_path / 'log', dry_run=True)
    assert result.executed is False
    assert result.commands_executed == 0


def test_real_execution_requires_root(tmp_path: Path) -> None:
    with pytest.raises(UserConfigurationError, match='root'):
        UserConfigurator(geteuid=lambda: 1000).execute(_plan(tmp_path), tmp_path / 'log')


def test_real_execution_validates_rootfs(tmp_path: Path) -> None:
    with pytest.raises(UserConfigurationError, match='falten'):
        UserConfigurator(geteuid=lambda: 0).execute(_plan(tmp_path), tmp_path / 'log')


def test_real_execution_runs_all_commands(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    for name in ('etc/debian_version', 'usr/sbin/groupadd', 'usr/sbin/useradd', 'usr/sbin/usermod', 'bin/bash'):
        path = plan.rootfs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    calls = []
    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)
    result = UserConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / 'log')
    assert result.executed is True
    assert result.commands_executed == len(plan.commands())
    assert calls == list(plan.commands())


def test_runner_error_is_wrapped(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    for name in ('etc/debian_version', 'usr/sbin/groupadd', 'usr/sbin/useradd', 'usr/sbin/usermod', 'bin/bash'):
        path = plan.rootfs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    def runner(command, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(7, command)
    with pytest.raises(UserConfigurationError, match='codi 7'):
        UserConfigurator(geteuid=lambda: 0, runner=runner).execute(plan, tmp_path / 'log')
