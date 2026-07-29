from pathlib import Path

REQUIRED_PATHS = (
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "VERSION",
    "pyproject.toml",
    "src/xaac_thin_client_os",
    "tests",
    "builder",
    "profiles/common",
    "profiles/wyse3040",
    "packages",
    "config",
    "recovery",
    "docs",
    "tools",
    "scripts",
    "Makefile",
)


def test_required_repository_paths_exist() -> None:
    missing = [path for path in REQUIRED_PATHS if not Path(path).exists()]
    assert not missing, f"Rutes obligatòries absents: {missing}"


def test_local_venv_is_ignored() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert ".venv/" in gitignore


def test_pycharm_files_are_ignored() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert ".idea/" in gitignore


def test_operational_scripts_exist_and_are_executable() -> None:
    scripts = (
        "create-venv.sh",
        "install-dev.sh",
        "run-tests.sh",
        "run-coverage.sh",
        "run-lint.sh",
        "clean.sh",
        "build.sh",
    )
    for script_name in scripts:
        script = Path("scripts") / script_name
        assert script.is_file(), f"Script absent: {script}"
        assert script.stat().st_mode & 0o111, f"Script no executable: {script}"


def test_makefile_exposes_standard_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    for target in ("venv:", "install:", "test:", "coverage:", "lint:", "build:", "clean:", "all:"):
        assert target in makefile


def test_phase_1_2_configuration_files_exist() -> None:
    required = (
        "config/build.yaml",
        "config/packages.yaml",
        "config/repositories.yaml",
        "profiles/common/profile.yaml",
        "profiles/wyse3040/profile.yaml",
        "docs/development/PHASE_1_2.md",
    )
    missing = [path for path in required if not Path(path).is_file()]
    assert not missing, f"Fitxers de configuració absents: {missing}"
