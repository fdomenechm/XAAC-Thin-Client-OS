from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Generated/build metadata is intentionally outside the source-policy check.
# In particular, editable installs may leave stale ``*.egg-info`` metadata
# from an older checkout even when the current source tree is already clean.
GENERATED_DIR_NAMES = {
    ".build",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
GENERATED_DIR_SUFFIXES = (".egg-info",)
BINARY_SUFFIXES = {".deb", ".ico", ".jpeg", ".jpg", ".png", ".webp"}


def _is_generated(candidate: Path) -> bool:
    relative = candidate.relative_to(ROOT)
    return any(
        part in GENERATED_DIR_NAMES or part.endswith(GENERATED_DIR_SUFFIXES)
        for part in relative.parts
    )


def test_generated_packaging_metadata_is_outside_source_policy() -> None:
    generated = ROOT / "src" / "package.egg-info" / "PKG-INFO"
    assert _is_generated(generated)


def test_retired_remote_support_component_is_absent() -> None:
    forbidden = ("rust" + "desk").lower()
    roots = [
        "README.md",
        "CHANGELOG.md",
        "config",
        "src",
        "scripts",
        "builder",
        "hooks",
        "docs",
        "tests",
        "packaging",
        "profiles",
        "templates",
        "recovery",
        "tools",
        "assets",
        "packages",
    ]
    hits = []
    for item in roots:
        path = ROOT / item
        candidates = [path] if path.is_file() else path.rglob("*") if path.exists() else []
        for candidate in candidates:
            if (
                not candidate.is_file()
                or _is_generated(candidate)
                or candidate.suffix.lower() in BINARY_SUFFIXES
            ):
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
