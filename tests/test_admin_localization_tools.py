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
        assert f'/usr/local/bin/{name}' in source
    assert 'helper_link.symlink_to(f"../sbin/{helper_name}")' in source
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


def _render_language_script_for_root(script_path: Path, root: Path) -> str:
    text = script_path.read_text(encoding="utf-8")
    return (
        text.replace("DEFAULT_LOCALE=/etc/default/locale", f"DEFAULT_LOCALE={root / 'etc/default/locale'}")
        .replace("SYSTEMD_LOCALE=/etc/locale.conf", f"SYSTEMD_LOCALE={root / 'etc/locale.conf'}")
        .replace("LOCALE_GEN_FILE=/etc/locale.gen", f"LOCALE_GEN_FILE={root / 'etc/locale.gen'}")
    )


def _fake_locale_commands(tmp_path: Path, locales: list[str], *, forbid_generation: bool = False) -> tuple[Path, Path]:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    state = tmp_path / "locales.txt"
    state.write_text("\n".join(locales) + "\n", encoding="utf-8")
    (fakebin / "locale").write_text(
        "#!/bin/sh\n[ \"${1:-}\" = '-a' ] || exit 2\ncat \"$XAAC_TEST_LOCALES\"\n",
        encoding="utf-8",
    )
    if forbid_generation:
        locale_gen = "#!/bin/sh\nexit 99\n"
    else:
        locale_gen = (
            "#!/bin/sh\n"
            "grep -Fqx 'ca_ES.utf8' \"$XAAC_TEST_LOCALES\" || "
            "printf '%s\\n' 'ca_ES.utf8' >> \"$XAAC_TEST_LOCALES\"\n"
        )
    (fakebin / "locale-gen").write_text(locale_gen, encoding="utf-8")
    # The production command intentionally requires root.  These functional
    # tests run the rendered helper against a temporary filesystem tree, so
    # emulate only the two privileged operations instead of requiring pytest
    # itself to run as root.
    (fakebin / "id").write_text(
        "#!/bin/sh\n[ \"${1:-}\" = '-u' ] && { echo 0; exit 0; }\nexec /usr/bin/id \"$@\"\n",
        encoding="utf-8",
    )
    (fakebin / "chown").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    for command in ("locale", "locale-gen", "id", "chown"):
        (fakebin / command).chmod(0o755)
    return fakebin, state


def test_language_set_accepts_debian_utf8_locale_name_and_updates_language(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "etc/default").mkdir(parents=True)
    (root / "etc/locale.conf").write_text("LANG=es_ES.UTF-8\nLANGUAGE=es_ES:es\n", encoding="utf-8")
    (root / "etc/default/locale").write_text("LANG=es_ES.UTF-8\nLANGUAGE=es_ES:es\n", encoding="utf-8")
    (root / "etc/locale.gen").write_text("ca_ES.UTF-8 UTF-8\nes_ES.UTF-8 UTF-8\n", encoding="utf-8")
    fakebin, state = _fake_locale_commands(tmp_path, ["C", "C.utf8", "ca_ES.utf8", "es_ES.utf8"], forbid_generation=True)
    rendered = tmp_path / "xaac-admin-change-language"
    rendered.write_text(_render_language_script_for_root(LANGUAGE, root), encoding="utf-8")
    rendered.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env['PATH']}"
    env["XAAC_TEST_LOCALES"] = str(state)

    result = subprocess.run([str(rendered), "set", "ca"], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    expected = "LANG=ca_ES.UTF-8\nLANGUAGE=ca_ES:ca\n"
    assert (root / "etc/default/locale").read_text(encoding="utf-8") == expected
    assert (root / "etc/locale.conf").read_text(encoding="utf-8") == expected


def test_language_set_generates_supported_locale_when_missing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "etc/default").mkdir(parents=True)
    (root / "etc/locale.conf").write_text("LANG=es_ES.UTF-8\nLANGUAGE=es_ES:es\n", encoding="utf-8")
    (root / "etc/default/locale").write_text("LANG=es_ES.UTF-8\nLANGUAGE=es_ES:es\n", encoding="utf-8")
    (root / "etc/locale.gen").write_text("# ca_ES.UTF-8 UTF-8\nes_ES.UTF-8 UTF-8\n", encoding="utf-8")
    fakebin, state = _fake_locale_commands(tmp_path, ["C", "C.utf8", "es_ES.utf8"])
    rendered = tmp_path / "xaac-admin-change-language"
    rendered.write_text(_render_language_script_for_root(LANGUAGE, root), encoding="utf-8")
    rendered.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env['PATH']}"
    env["XAAC_TEST_LOCALES"] = str(state)

    result = subprocess.run([str(rendered), "set", "ca"], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "ca_ES.UTF-8 UTF-8" in (root / "etc/locale.gen").read_text(encoding="utf-8").splitlines()
    assert "ca_ES.utf8" in state.read_text(encoding="utf-8").splitlines()
    assert "LANGUAGE=ca_ES:ca" in (root / "etc/default/locale").read_text(encoding="utf-8")
