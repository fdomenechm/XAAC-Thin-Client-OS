from __future__ import annotations
import subprocess
from pathlib import Path
import pytest
from xaac_thin_client_os.localization import LocalizationConfigurator, LocalizationError, create_localization_plan

def _cfg(path: Path, extra: str='') -> Path:
    path.write_text('''schema_version: 1
locale: ca_ES.UTF-8
fallback_locales:
  - es_ES.UTF-8
  - en_US.UTF-8
timezone: Europe/Madrid
keyboard:
  model: pc105
  layout: es
  variant: cat
  options: []
console:
  charmap: UTF-8
  font: Lat15-Terminus16
'''+extra,encoding='utf-8'); return path

def _plan(tmp_path: Path): return create_localization_plan(tmp_path/'runs/build/rootfs',_cfg(tmp_path/'localization.yaml'))
def _prepare(plan):
    for p in (plan.rootfs/'etc/debian_version',plan.rootfs/'usr/sbin/locale-gen',plan.rootfs/'usr/sbin/update-locale',plan.rootfs/'usr/share/zoneinfo/Europe/Madrid'):
        p.parent.mkdir(parents=True,exist_ok=True); p.write_text('ok\n')

def test_plan_loads_expected_values(tmp_path):
    p=_plan(tmp_path); assert p.locale=='ca_ES.UTF-8'; assert p.keyboard_layout=='es'; assert p.keyboard_variant=='cat'; assert len(p.locales)==3

def test_manifest_is_stable(tmp_path):
    p=_plan(tmp_path); assert p.to_manifest()['console']['charmap']=='UTF-8'; assert len(p.commands())==2

def test_rejects_unsafe_rootfs(tmp_path):
    with pytest.raises(LocalizationError,match='insegura'): create_localization_plan(Path('/rootfs'),_cfg(tmp_path/'c'))

def test_rejects_unknown_key(tmp_path):
    with pytest.raises(LocalizationError,match='desconegudes'): create_localization_plan(tmp_path/'runs/b/rootfs',_cfg(tmp_path/'c','unknown: true\n'))

def test_rejects_bad_locale(tmp_path):
    p=_cfg(tmp_path/'c'); p.write_text(p.read_text().replace('ca_ES.UTF-8','ca_ES'))
    with pytest.raises(LocalizationError,match='Locale'): create_localization_plan(tmp_path/'runs/b/rootfs',p)

def test_rejects_bad_keyboard_options(tmp_path):
    p=_cfg(tmp_path/'c'); p.write_text(p.read_text().replace('options: []','options: invalid'))
    with pytest.raises(LocalizationError,match='options'): create_localization_plan(tmp_path/'runs/b/rootfs',p)

def test_dry_run_needs_no_root(tmp_path):
    r=LocalizationConfigurator(geteuid=lambda:1000).execute(_plan(tmp_path),tmp_path/'log',dry_run=True); assert not r.executed; assert r.commands_executed==0

def test_real_requires_root(tmp_path):
    with pytest.raises(LocalizationError,match='root'): LocalizationConfigurator(geteuid=lambda:1000).execute(_plan(tmp_path),tmp_path/'log')

def test_real_requires_files(tmp_path):
    with pytest.raises(LocalizationError,match='falten'): LocalizationConfigurator(geteuid=lambda:0).execute(_plan(tmp_path),tmp_path/'log')

def test_real_writes_all_files_and_commands(tmp_path):
    p=_plan(tmp_path); _prepare(p); calls=[]
    def runner(command,**kwargs): calls.append(tuple(command)); return subprocess.CompletedProcess(command,0)
    r=LocalizationConfigurator(geteuid=lambda:0,runner=runner).execute(p,tmp_path/'log')
    assert r.executed and r.commands_executed==2 and calls==list(p.commands())
    assert 'XKBVARIANT="cat"' in (p.rootfs/'etc/default/keyboard').read_text()
    assert (p.rootfs/'etc/localtime').is_symlink()

def test_symlink_destination_rejected(tmp_path):
    p=_plan(tmp_path); _prepare(p); target=p.rootfs/'etc/default/keyboard'; target.parent.mkdir(parents=True,exist_ok=True); target.symlink_to('/tmp/x')
    with pytest.raises(LocalizationError,match='simbòlic'): LocalizationConfigurator(geteuid=lambda:0).execute(p,tmp_path/'log')

def test_command_error_wrapped(tmp_path):
    p=_plan(tmp_path); _prepare(p)
    def runner(command,**kwargs): raise subprocess.CalledProcessError(5,command)
    with pytest.raises(LocalizationError,match='codi 5'): LocalizationConfigurator(geteuid=lambda:0,runner=runner).execute(p,tmp_path/'log')


def test_default_locale_internal_symlink_is_supported(tmp_path):
    p=_plan(tmp_path); _prepare(p)
    target=p.rootfs/'etc/default/locale'; target.parent.mkdir(parents=True,exist_ok=True); target.symlink_to('/etc/locale.conf')
    def runner(command,**kwargs): return subprocess.CompletedProcess(command,0)
    LocalizationConfigurator(geteuid=lambda:0,runner=runner).execute(p,tmp_path/'log')
    assert target.is_symlink()
    assert 'LANG="ca_ES.UTF-8"' in (p.rootfs/'etc/locale.conf').read_text()
