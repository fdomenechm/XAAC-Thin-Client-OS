"""Deterministic locale, keyboard, timezone and console configuration."""
from __future__ import annotations
import os, re, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import yaml

class LocalizationError(RuntimeError):
    """Raised when localization cannot be planned or applied."""

_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}_[A-Za-z]{2,3}\.UTF-8$")
_SAFE_RE = re.compile(r"^[A-Za-z0-9_+.,:@/-]*$")

@dataclass(frozen=True, slots=True)
class LocalizationPlan:
    rootfs: Path; locale: str; fallback_locales: tuple[str, ...]; timezone: str
    keyboard_model: str; keyboard_layout: str; keyboard_variant: str
    keyboard_options: tuple[str, ...]; console_charmap: str; console_font: str
    @property
    def locales(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.locale, *self.fallback_locales)))
    def commands(self) -> tuple[tuple[str, ...], ...]:
        return (("chroot", str(self.rootfs), "/usr/sbin/locale-gen"),
                ("chroot", str(self.rootfs), "/usr/sbin/update-locale", f"LANG={self.locale}"))
    def to_manifest(self) -> dict[str, object]:
        return {"rootfs": str(self.rootfs), "locale": self.locale, "fallback_locales": list(self.fallback_locales),
                "timezone": self.timezone, "keyboard": {"model": self.keyboard_model, "layout": self.keyboard_layout,
                "variant": self.keyboard_variant, "options": list(self.keyboard_options)},
                "console": {"charmap": self.console_charmap, "font": self.console_font},
                "commands": [list(c) for c in self.commands()]}

@dataclass(frozen=True, slots=True)
class LocalizationResult:
    executed: bool; log_path: Path; files_written: tuple[Path, ...]; commands_executed: int

def _text(value: object, name: str, *, allow_empty: bool=False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise LocalizationError(f"{name} ha de ser text {'vàlid' if allow_empty else 'no buit'}")
    value=value.strip()
    if not _SAFE_RE.fullmatch(value) or ".." in value:
        raise LocalizationError(f"{name} no és segur")
    return value

def create_localization_plan(rootfs: Path, config_path: Path) -> LocalizationPlan:
    rootfs=rootfs.resolve()
    if rootfs == Path('/') or rootfs.name != 'rootfs' or rootfs.parent.parent.name != 'runs':
        raise LocalizationError('Ruta rootfs insegura')
    try: raw=yaml.safe_load(config_path.read_text(encoding='utf-8'))
    except (OSError,yaml.YAMLError) as exc: raise LocalizationError(f"No es pot llegir {config_path}: {exc}") from exc
    if not isinstance(raw,dict) or raw.get('schema_version') != 1: raise LocalizationError('Esquema de localització no suportat')
    allowed={'schema_version','locale','fallback_locales','timezone','keyboard','console'}
    if set(raw)-allowed: raise LocalizationError('Claus desconegudes en localization.yaml')
    locale=_text(raw.get('locale'),'locale'); fallbacks=raw.get('fallback_locales',[])
    if not isinstance(fallbacks,list) or not all(isinstance(x,str) for x in fallbacks): raise LocalizationError('fallback_locales ha de ser una llista')
    fallbacks=tuple(x.strip() for x in fallbacks)
    if any(not _LOCALE_RE.fullmatch(x) for x in (locale,*fallbacks)): raise LocalizationError('Locale no vàlida')
    timezone=_text(raw.get('timezone'),'timezone')
    keyboard=raw.get('keyboard'); console=raw.get('console')
    if not isinstance(keyboard,dict) or set(keyboard)-{'model','layout','variant','options'}: raise LocalizationError('Configuració de teclat no vàlida')
    if not isinstance(console,dict) or set(console)-{'charmap','font'}: raise LocalizationError('Configuració de consola no vàlida')
    options=keyboard.get('options',[])
    if not isinstance(options,list) or not all(isinstance(x,str) for x in options): raise LocalizationError('keyboard.options ha de ser una llista')
    return LocalizationPlan(rootfs,locale,fallbacks,timezone,_text(keyboard.get('model'),'keyboard.model'),
        _text(keyboard.get('layout'),'keyboard.layout'),_text(keyboard.get('variant',''),'keyboard.variant',allow_empty=True),
        tuple(_text(x,'keyboard.option') for x in options),_text(console.get('charmap'),'console.charmap'),_text(console.get('font'),'console.font'))

class LocalizationConfigurator:
    def __init__(self, *, geteuid: Callable[[],int]=os.geteuid, runner: Callable[...,subprocess.CompletedProcess[str]]=subprocess.run):
        self._geteuid=geteuid; self._runner=runner
    @staticmethod
    def _safe_write_target(rootfs: Path, path: Path) -> Path:
        if not path.is_symlink(): return path
        link=Path(os.readlink(path))
        candidate=(rootfs/link.relative_to('/')) if link.is_absolute() else (path.parent/link)
        candidate=candidate.resolve(strict=False)
        allowed=(rootfs/'etc/locale.conf').resolve(strict=False)
        if path != rootfs/'etc/default/locale' or candidate != allowed:
            raise LocalizationError(f"No s'escriurà sobre l'enllaç simbòlic {path}")
        return candidate
    @classmethod
    def _write(cls, rootfs: Path, path: Path, content: str) -> None:
        target=cls._safe_write_target(rootfs,path)
        target.parent.mkdir(parents=True,exist_ok=True); tmp=target.with_name(target.name+'.tmp')
        if tmp.is_symlink(): raise LocalizationError(f"No s'escriurà sobre l'enllaç simbòlic {tmp}")
        tmp.write_text(content,encoding='utf-8'); tmp.replace(target)
    def execute(self, plan: LocalizationPlan, log_path: Path, *, dry_run: bool=False) -> LocalizationResult:
        files=(plan.rootfs/'etc/locale.gen',plan.rootfs/'etc/default/locale',plan.rootfs/'etc/default/keyboard',
               plan.rootfs/'etc/default/console-setup',plan.rootfs/'etc/timezone',plan.rootfs/'etc/localtime')
        log_path.parent.mkdir(parents=True,exist_ok=True)
        with log_path.open('w',encoding='utf-8') as log:
            log.write(('DRY-RUN' if dry_run else 'EXECUTE')+' localization\n')
            for c in plan.commands(): log.write('command='+' '.join(c)+'\n')
            if dry_run: return LocalizationResult(False,log_path,files,0)
            if self._geteuid()!=0: raise LocalizationError('La configuració real requereix privilegis de root')
            required=(plan.rootfs/'etc/debian_version',plan.rootfs/'usr/sbin/locale-gen',plan.rootfs/'usr/sbin/update-locale',plan.rootfs/'usr/share/zoneinfo'/plan.timezone)
            missing=[str(p) for p in required if not p.exists()]
            if missing: raise LocalizationError('Al rootfs falten requisits: '+', '.join(missing))
            self._write(plan.rootfs,files[0],''.join(f'{x} UTF-8\n' for x in plan.locales))
            self._write(plan.rootfs,files[1],f'LANG="{plan.locale}"\nLANGUAGE="{plan.locale.split(".")[0]}"\n')
            self._write(plan.rootfs,files[2],f'XKBMODEL="{plan.keyboard_model}"\nXKBLAYOUT="{plan.keyboard_layout}"\nXKBVARIANT="{plan.keyboard_variant}"\nXKBOPTIONS="{",".join(plan.keyboard_options)}"\nBACKSPACE="guess"\n')
            self._write(plan.rootfs,files[3],f'CHARMAP="{plan.console_charmap}"\nCODESET="guess"\nFONTFACE="Fixed"\nFONTSIZE="16"\nFONT="{plan.console_font}"\n')
            self._write(plan.rootfs,files[4],plan.timezone+'\n')
            if files[5].exists() or files[5].is_symlink(): files[5].unlink()
            files[5].symlink_to(Path('/usr/share/zoneinfo')/plan.timezone)
            count=0
            for command in plan.commands():
                try: self._runner(command,check=True,stdout=log,stderr=subprocess.STDOUT,text=True); count+=1
                except subprocess.CalledProcessError as exc: raise LocalizationError(f"Ordre de localització fallida amb codi {exc.returncode}") from exc
                except OSError as exc: raise LocalizationError(f"No s'ha pogut executar la configuració: {exc}") from exc
        return LocalizationResult(True,log_path,files,count)
