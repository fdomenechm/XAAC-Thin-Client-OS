from pathlib import Path
import yaml


def test_svg_loader_is_installed_by_production_package_resolution():
    stack = yaml.safe_load(Path("config/graphical-stack.yaml").read_text(encoding="utf-8"))
    packages = yaml.safe_load(Path("config/packages.yaml").read_text(encoding="utf-8"))
    assert "librsvg2-common" in stack["packages"]["required"]
    assert "librsvg2-common" in packages["graphical"]
