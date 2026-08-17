from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

def test_retired_remote_support_component_is_absent() -> None:
    forbidden = ("rust" + "desk").lower()
    roots = ["README.md", "CHANGELOG.md", "config", "src", "scripts", "builder", "hooks", "docs", "tests", "packaging", "profiles", "templates", "recovery", "tools", "assets", "packages"]
    hits = []
    for item in roots:
        path = ROOT / item
        candidates = [path] if path.is_file() else path.rglob("*") if path.exists() else []
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix in {".deb", ".png", ".jpg", ".jpeg", ".webp", ".ico"}:
                continue
            if forbidden in candidate.name.lower():
                hits.append(str(candidate.relative_to(ROOT)))
                continue
            try:
                content = candidate.read_text(encoding="utf-8").lower()
            except (UnicodeDecodeError, OSError):
                continue
            if forbidden in content:
                hits.append(str(candidate.relative_to(ROOT)))
    assert hits == []
