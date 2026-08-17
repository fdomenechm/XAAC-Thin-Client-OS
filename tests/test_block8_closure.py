from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_block8_appliance_document_is_closed() -> None:
    text = (ROOT / "docs/development/APPLIANCE_EXPERIENCE.md").read_text()

    assert "**Estat:** **TANCAT**" in text
    assert "## Fase 8.6 — Consolidació i tancament" in text
    assert "**Bloc 8 tancat.**" in text
    assert "## Àrees pendents del Bloc 8" not in text


def test_block8_final_visual_contract_is_documented() -> None:
    text = (ROOT / "docs/development/APPLIANCE_EXPERIENCE.md").read_text()

    assert "#383e42" in text
    assert "cursor `wait`" in text
    assert "instal·lador en català" in text
    assert "XAAC Thin Client VPN" in text


def test_obsolete_historical_block8_is_removed() -> None:
    assert not (ROOT / "docs/phases/block-08").exists()


def test_block8_validator_reports_final_closure() -> None:
    text = (ROOT / "scripts/validate-block8-visual.sh").read_text()

    assert "tests/test_block8_closure.py" in text
    assert "Bloc 8 tancat (Fase 8.6)" in text
