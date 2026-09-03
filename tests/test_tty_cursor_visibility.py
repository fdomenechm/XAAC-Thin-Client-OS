from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_boot_keeps_global_cursor_hidden_for_splash() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "vt.global_cursor_default=0" in source


def test_getty_restores_visible_cursor_on_text_ttys() -> None:
    source = (ROOT / "src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")
    assert "20-xaac-visible-cursor.conf" in source
    assert r'\033[?25h' in source
    assert "show-tty-cursor %I" in source
    assert "show-tty-cursor" in source
    assert "20-xaac-visible-tty-cursor.sh" in source
