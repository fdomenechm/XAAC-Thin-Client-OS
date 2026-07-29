from pathlib import Path

import pytest

from xaac_thin_client_os.templates import (
    TemplateError,
    TemplatePathError,
    TemplateRenderer,
    TemplateVariableError,
    render_text,
)


def test_render_text_supports_dotted_variables_and_boolean() -> None:
    rendered, variables = render_text(
        "name={{ project.name }} enabled={{ enabled }}",
        {"project": {"name": "XAAC"}, "enabled": True},
    )
    assert rendered == "name=XAAC enabled=true"
    assert variables == ("project.name", "enabled")


def test_render_text_rejects_missing_variable() -> None:
    with pytest.raises(TemplateVariableError, match="missing"):
        render_text("{{ missing }}", {})


def test_render_text_rejects_non_scalar_variable() -> None:
    with pytest.raises(TemplateVariableError, match="escalar"):
        render_text("{{ packages }}", {"packages": ["apt"]})


def test_render_text_rejects_unsupported_expression() -> None:
    with pytest.raises(TemplateError, match="no vàlida"):
        render_text("{{ package | upper }}", {"package": "apt"})


def test_renderer_writes_atomically_and_is_idempotent(tmp_path: Path) -> None:
    template_root = tmp_path / "templates"
    destination_root = tmp_path / "output"
    template_root.mkdir()
    (template_root / "sample.tpl").write_text("value={{ value }}\n", encoding="utf-8")
    renderer = TemplateRenderer(template_root, destination_root)
    first = renderer.render_file(Path("sample.tpl"), Path("etc/sample"), {"value": 3})
    second = renderer.render_file(Path("sample.tpl"), Path("etc/sample"), {"value": 3})
    assert first.changed is True
    assert second.changed is False
    assert (destination_root / "etc/sample").read_text(encoding="utf-8") == "value=3\n"
    assert not (destination_root / "etc/.sample.tmp").exists()


def test_renderer_rejects_unsafe_paths(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    root.mkdir()
    (root / "sample.tpl").write_text("ok", encoding="utf-8")
    renderer = TemplateRenderer(root, tmp_path / "output")
    with pytest.raises(TemplatePathError):
        renderer.render_file(Path("../secret.tpl"), Path("out"), {})
    with pytest.raises(TemplatePathError):
        renderer.render_file(Path("sample.tpl"), Path("../out"), {})


def test_render_tree_preserves_structure_and_order(tmp_path: Path) -> None:
    template_root = tmp_path / "templates"
    (template_root / "etc").mkdir(parents=True)
    (template_root / "z.tpl").write_text("z", encoding="utf-8")
    (template_root / "etc/a.tpl").write_text("{{ value }}", encoding="utf-8")
    renderer = TemplateRenderer(template_root, tmp_path / "output")
    results = renderer.render_tree({"value": "a"})
    assert [item.destination.relative_to(tmp_path / "output") for item in results] == [
        Path("etc/a"),
        Path("z"),
    ]


def test_render_tree_requires_template_directory(tmp_path: Path) -> None:
    with pytest.raises(TemplateError, match="directori"):
        TemplateRenderer(tmp_path / "missing", tmp_path / "output").render_tree({})
