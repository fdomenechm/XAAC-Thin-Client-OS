from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


def render_production_installer(project_root: Path | None = None) -> str:
    root = project_root or Path(__file__).resolve().parents[1]
    source_path = root / "src/xaac_thin_client_os/production_builder.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        target = ast.get_source_segment(source, node.args[0]) or ""
        if "xaac-installer-welcome" not in target or "service" in target:
            continue
        return eval(
            compile(ast.Expression(node.args[1]), str(source_path), "eval"),
            {
                "installed_kernel_cmdline": "quiet splash loglevel=0",
                "self": SimpleNamespace(settings=SimpleNamespace(locale="ca_ES.UTF-8")),
            },
        )
    raise AssertionError("production installer script not found")
