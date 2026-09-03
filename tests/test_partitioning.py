from pathlib import Path
import subprocess
import pytest
from xaac_thin_client_os.partitioning import PartitionConfigurator, PartitioningError, create_partition_plan


def config(tmp_path: Path, text: str | None = None) -> Path:
    source = Path('config/partitions.yaml').read_text() if text is None else text
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / 'partitions.yaml'; path.write_text(source); return path


def test_plan_has_four_aligned_partitions_and_deterministic_commands(tmp_path: Path) -> None:
    plan = create_partition_plan(tmp_path / 'run/rootfs', config(tmp_path), Path('/dev/mmcblk0'))
    assert [p.label for p in plan.partitions] == ['XAAC_EFI','XAAC_ROOT','XAAC_DATA','XAAC_RECOVERY']
    assert plan.partition_path(1) == Path('/dev/mmcblk0p1')
    assert len(plan.commands) == 10
    assert plan.commands[0][:2] == ('sgdisk','--zap-all')
    assert 'LABEL=XAAC_ROOT\t/\text4\tdefaults,noatime\t0\t1' in plan.fstab_content()


def test_sata_partition_naming(tmp_path: Path) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/sda'))
    assert plan.partition_path(4) == Path('/dev/sda4')


def test_dry_run_is_non_destructive(tmp_path: Path) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/mmcblk0'))
    result = PartitionConfigurator(geteuid=lambda: 1000).execute(plan, tmp_path/'part.log', dry_run=True)
    assert not result.executed and not plan.fstab_path.exists()
    assert 'sgdisk' in result.log_path.read_text()


def test_real_execution_requires_explicit_confirmation(tmp_path: Path) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/mmcblk0'))
    with pytest.raises(PartitioningError, match='confirm-destructive'):
        PartitionConfigurator().execute(plan, tmp_path/'part.log')


def test_requires_root_after_confirmation(tmp_path: Path) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/mmcblk0'))
    with pytest.raises(PartitioningError, match='privilegis'):
        PartitionConfigurator(geteuid=lambda: 1000).execute(plan, tmp_path/'part.log', confirm_destructive=True)


@pytest.mark.parametrize('text,match', [
    ('schema: mbr\ndisk_size_mib: 7168\nalignment_mib: 1\npartitions: []\n','schema'),
    ('schema: gpt\ndisk_size_mib: 1000\nalignment_mib: 1\npartitions: []\n','disk_size_mib'),
    ('schema: gpt\ndisk_size_mib: 7168\nalignment_mib: 0\npartitions: []\n','alignment_mib'),
    ('schema: gpt\ndisk_size_mib: 7168\nalignment_mib: 1\npartitions: []\n','quatre'),
    ('- bad\n','mapa YAML'),
    ('schema: gpt\ndisk_size_mib: 7168\nalignment_mib: 1\npartitions: []\nunknown: true\n','Claus desconegudes'),
])
def test_invalid_top_level_configuration(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(PartitioningError, match=match):
        create_partition_plan(tmp_path/'rootfs', config(tmp_path,text), Path('/dev/sda'))


def test_rejects_unsafe_device(tmp_path: Path) -> None:
    with pytest.raises(PartitioningError, match='/dev'):
        create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/tmp/disk'))


def test_rejects_oversized_layout(tmp_path: Path) -> None:
    text = Path('config/partitions.yaml').read_text().replace('size_mib: 4608','size_mib: 6000')
    with pytest.raises(PartitioningError, match='excedeixen'):
        create_partition_plan(tmp_path/'rootfs', config(tmp_path,text), Path('/dev/sda'))


def test_command_failure_is_wrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/sda'))
    monkeypatch.setattr(Path, 'is_block_device', lambda self: True)
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    def runner(command, **kwargs): raise subprocess.CalledProcessError(4, command)
    with pytest.raises(PartitioningError, match='codi 4'):
        PartitionConfigurator(geteuid=lambda: 0, runner=runner).execute(plan,tmp_path/'log',confirm_destructive=True)


def test_manifest_contains_partition_layout(tmp_path: Path) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/sda'))
    manifest = plan.to_manifest()
    assert manifest['disk_size_mib'] == 7168
    assert len(manifest['partitions']) == 4

def test_real_execution_writes_fstab_and_runs_all_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/sda'))
    monkeypatch.setattr(Path, 'is_block_device', lambda self: True)
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    calls = []
    def runner(command, **kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)
    result = PartitionConfigurator(geteuid=lambda: 0, runner=runner).execute(
        plan, tmp_path/'log', confirm_destructive=True
    )
    assert result.executed
    assert result.commands_executed == len(plan.commands)
    assert len(calls) == len(plan.commands)
    assert plan.fstab_path.read_text().startswith('# XAAC')


def test_oserror_is_wrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/sda'))
    monkeypatch.setattr(Path, 'is_block_device', lambda self: True)
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    def runner(command, **kwargs): raise OSError('missing')
    with pytest.raises(PartitioningError, match="No s'ha pogut executar"):
        PartitionConfigurator(geteuid=lambda: 0, runner=runner).execute(
            plan, tmp_path/'log', confirm_destructive=True
        )


def test_rejects_non_block_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/sda'))
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    monkeypatch.setattr(Path, 'is_block_device', lambda self: False)
    with pytest.raises(PartitioningError, match='no és de bloc'):
        PartitionConfigurator(geteuid=lambda: 0).execute(
            plan, tmp_path/'log', confirm_destructive=True
        )


def test_rejects_symlinked_fstab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = create_partition_plan(tmp_path/'rootfs', config(tmp_path), Path('/dev/sda'))
    monkeypatch.setattr(Path, 'is_block_device', lambda self: True)
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    plan.fstab_path.parent.mkdir(parents=True)
    plan.fstab_path.symlink_to(tmp_path/'target')
    def runner(command, **kwargs): return subprocess.CompletedProcess(command, 0)
    with pytest.raises(PartitioningError, match='enllaç simbòlic'):
        PartitionConfigurator(geteuid=lambda: 0, runner=runner).execute(
            plan, tmp_path/'log', confirm_destructive=True
        )


def test_rejects_invalid_partition_fields(tmp_path: Path) -> None:
    base = Path('config/partitions.yaml').read_text()
    cases = [
        (base.replace('number: 2', 'number: 1'), 'duplicat'),
        (base.replace('size_mib: 256', 'size_mib: 32'), 'almenys 64'),
        (base.replace('label: XAAC_ROOT', 'label: bad-label'), 'Etiqueta'),
        (base.replace('type_code: "8304"', 'type_code: ZZZZ'), 'type_code'),
        (base.replace('filesystem: ext4', 'filesystem: xfs', 1), 'filesystem'),
        (base.replace('mountpoint: /var/lib/xaac', 'mountpoint: /'), 'muntatge'),
        (base.replace('options: defaults,noatime', 'options: "bad option"', 1), 'Opcions'),
        (base.replace('  - name: root\n', '  - unexpected: true\n    name: root\n'), 'Camps'),
    ]
    for index, (text, match) in enumerate(cases):
        with pytest.raises(PartitioningError, match=match):
            create_partition_plan(tmp_path/f'r{index}', config(tmp_path/f'c{index}', text), Path('/dev/sda'))
