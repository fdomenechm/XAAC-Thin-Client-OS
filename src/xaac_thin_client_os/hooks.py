"""Controlled build hook discovery and execution."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping


class HookError(RuntimeError):
    """Base error raised by the hook subsystem."""


class HookPermissionError(HookError):
    """Raised when a hook exists but is not safely executable."""


class HookExecutionError(HookError):
    """Raised when a hook exits unsuccessfully."""


class HookTimeoutError(HookError):
    """Raised when a hook exceeds its execution timeout."""


class HookPhase(StrEnum):
    """Supported build hook phases in deterministic order."""

    PRE_BOOTSTRAP = "pre-bootstrap"
    POST_BOOTSTRAP = "post-bootstrap"
    PRE_PACKAGES = "pre-packages"
    POST_PACKAGES = "post-packages"
    PRE_IMAGE = "pre-image"
    POST_IMAGE = "post-image"


HOOK_PHASES: tuple[HookPhase, ...] = tuple(HookPhase)


@dataclass(frozen=True, slots=True)
class HookResult:
    """Result of one successfully executed hook."""

    phase: HookPhase
    name: str
    path: Path
    log_path: Path
    return_code: int


class HookRunner:
    """Discover and execute project hooks with strict safety controls."""

    def __init__(
        self,
        project_root: Path,
        logs_dir: Path,
        *,
        timeout_seconds: float = 60.0,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("El timeout dels hooks ha de ser superior a zero")
        self.project_root = project_root.resolve()
        self.hooks_root = self.project_root / "hooks"
        self.logs_dir = logs_dir.resolve()
        self.timeout_seconds = timeout_seconds
        self.environment = dict(environment or {})

    def discover(self, phase: HookPhase) -> tuple[Path, ...]:
        """Return executable hook files for a phase in lexical order."""
        phase_dir = self.hooks_root / phase.value
        if not phase_dir.exists():
            return ()
        if not phase_dir.is_dir():
            raise HookError(f"La ruta de hooks no és un directori: {phase_dir}")

        hooks: list[Path] = []
        for path in sorted(phase_dir.iterdir(), key=lambda item: item.name):
            if path.name.startswith(".") or path.name == "README.md" or not path.is_file():
                continue
            if path.is_symlink():
                raise HookPermissionError(f"No es permeten hooks simbòlics: {path}")
            if not os.access(path, os.X_OK):
                raise HookPermissionError(f"El hook no té permís d'execució: {path}")
            hooks.append(path)
        return tuple(hooks)

    def run_phase(self, phase: HookPhase) -> tuple[HookResult, ...]:
        """Execute all hooks belonging to one phase."""
        return tuple(self._run_hook(phase, hook) for hook in self.discover(phase))

    def run_all(self) -> tuple[HookResult, ...]:
        """Execute every supported phase in its declared order."""
        results: list[HookResult] = []
        for phase in HOOK_PHASES:
            results.extend(self.run_phase(phase))
        return tuple(results)

    def _run_hook(self, phase: HookPhase, hook: Path) -> HookResult:
        phase_log_dir = self.logs_dir / "hooks" / phase.value
        phase_log_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
        log_path = phase_log_dir / f"{hook.name}.log"
        environment = os.environ.copy()
        environment.update(self.environment)
        environment.update(
            {
                "XAAC_HOOK_PHASE": phase.value,
                "XAAC_PROJECT_ROOT": str(self.project_root),
            }
        )
        try:
            completed = subprocess.run(
                [str(hook)],
                cwd=self.project_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + (exc.stderr or "")
            log_path.write_text(output, encoding="utf-8")
            raise HookTimeoutError(
                f"El hook {hook.name} ha superat el timeout de {self.timeout_seconds:g} segons"
            ) from exc
        except OSError as exc:
            raise HookExecutionError(f"No s'ha pogut executar el hook {hook}: {exc}") from exc

        log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise HookExecutionError(
                f"El hook {hook.name} ({phase.value}) ha finalitzat amb codi {completed.returncode}"
            )
        return HookResult(phase, hook.name, hook, log_path, completed.returncode)
