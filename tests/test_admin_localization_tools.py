from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LANGUAGE = ROOT / "assets/runtime/xaac-admin-change-language"
KEYBOARD = ROOT / "assets/runtime/xaac-admin-change-keyboard"


def test_admin_localization_scripts_are_posix_and_have_stable_cli() -> None:
    for script in (LANGUAGE, KEYBOARD):
        subprocess.run(["/bin/sh", "-n", str(script)], check=True)
        out = subprocess.run([str(script), "--help"], check=True, capture_output=True, text=True).stdout
        assert " get" in out
        assert " list" in out
        assert " set <" in out
        assert "--help" in out


def test_language_lists_only_locales_generated_by_the_image() -> None:
    out = subprocess.run([str(LANGUAGE), "list"], check=True, capture_output=True, text=True).stdout.splitlines()
    assert out == ["ca", "es", "en"]


def test_keyboard_lists_installed_xkb_layout_candidates() -> None:
    out = subprocess.run([str(KEYBOARD), "list"], check=True, capture_output=True, text=True).stdout.splitlines()
    assert out[:2] == ["es", "us"]
    assert {"gb", "fr", "de", "it", "pt"}.issubset(out)


def test_production_builder_installs_and_verifies_admin_localization_tools() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    for name in ("xaac-admin-change-language", "xaac-admin-change-keyboard"):
        assert f'"{name}"' in source
        assert f'/usr/local/sbin/{name}' in source
    assert "configure-localization-admin-tools" in source


def test_documentation_covers_both_admin_localization_tools() -> None:
    doc = (ROOT / "docs/administration/localization.md").read_text(encoding="utf-8")
    for name in ("xaac-admin-change-language", "xaac-admin-change-keyboard"):
        assert name in doc
    for command in ("get", "list", "set", "--help"):
        assert command in doc
    assert "/etc/default/locale" in doc
    assert "/etc/default/keyboard" in doc
    assert "reinici" in doc.lower()
