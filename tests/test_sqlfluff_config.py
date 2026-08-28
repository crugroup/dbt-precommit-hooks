from __future__ import annotations

from pathlib import Path

import pytest

from dbt_precommit_hooks import sqlfluff_config

PYPROJECT = """
[tool.sqlfluff.core]
templater = "dbt"
dialect = "snowflake"
exclude_rules = ["CP01", "AL01"]
max_line_length = 30

[tool.sqlfluff.indentation]
tab_space_size = 8

[tool.sqlfluff.layout.type.comma]
line_position = "leading"

[tool.sqlfluff.rules.capitalisation.keywords]
capitalisation_policy = "lower"
"""


def write_pyproject(directory: Path, body: str = PYPROJECT) -> Path:
    path = directory / "pyproject.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_read_config_returns_the_tool_sqlfluff_table(tmp_path: Path) -> None:
    config = sqlfluff_config.read_config(write_pyproject(tmp_path))

    assert config["core"]["dialect"] == "snowflake"
    assert config["indentation"] == {"tab_space_size": 8}


def test_read_config_without_sqlfluff_table(tmp_path: Path) -> None:
    assert sqlfluff_config.read_config(write_pyproject(tmp_path, "[project]\nname = 'x'\n")) == {}


def test_read_config_reports_broken_toml(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="cannot parse"):
        sqlfluff_config.read_config(write_pyproject(tmp_path, "[tool.sqlfluff\n"))


def test_find_pyproject_walks_up_to_the_nearest_config(tmp_path: Path) -> None:
    pyproject = write_pyproject(tmp_path)
    project_dir = tmp_path / "dbt"
    project_dir.mkdir()

    assert sqlfluff_config.find_pyproject(project_dir) == pyproject


def test_find_pyproject_skips_files_without_sqlfluff_config(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_pyproject(root, "[project]\nname = 'x'\n")

    assert sqlfluff_config.find_pyproject(root) is None


def test_render_sqlfluff_maps_tables_onto_ini_sections(tmp_path: Path) -> None:
    rendered = sqlfluff_config.render_sqlfluff(
        sqlfluff_config.read_config(write_pyproject(tmp_path))
    )

    # ``core`` is the top-level section; nested tables are ``:``-joined.
    assert "[sqlfluff]\n" in rendered
    assert "templater = dbt\n" in rendered
    assert "exclude_rules = CP01,AL01\n" in rendered
    assert "[sqlfluff:indentation]\ntab_space_size = 8\n" in rendered
    assert "[sqlfluff:layout:type:comma]\nline_position = leading\n" in rendered
    assert "[sqlfluff:rules:capitalisation:keywords]\ncapitalisation_policy = lower\n" in rendered
    assert "[sqlfluff:core]" not in rendered


def test_render_sqlfluff_formats_scalars() -> None:
    rendered = sqlfluff_config.render_sqlfluff({"core": {"large_file_skip_byte_limit": 0}})
    assert "large_file_skip_byte_limit = 0\n" in rendered

    rendered = sqlfluff_config.render_sqlfluff({"core": {"nocolor": True}})
    assert "nocolor = true\n" in rendered


def test_sqlfluff_config_file_writes_and_cleans_up(tmp_path: Path) -> None:
    config = sqlfluff_config.read_config(write_pyproject(tmp_path))

    with sqlfluff_config.sqlfluff_config_file(config) as path:
        assert path.name == ".sqlfluff"
        assert path.read_text(encoding="utf-8") == sqlfluff_config.render_sqlfluff(config)

    assert not path.exists()


def test_layout_flags_translates_the_format_subset(tmp_path: Path) -> None:
    config = sqlfluff_config.read_config(write_pyproject(tmp_path))

    assert sqlfluff_config.layout_flags(config) == [
        "-l",
        "indent=8",
        "-l",
        "line-length=30",
        "-l",
        "commas=leading",
    ]


def test_layout_flags_skips_unset_options() -> None:
    assert sqlfluff_config.layout_flags({}) == []
    assert sqlfluff_config.layout_flags({"core": {"max_line_length": 80}}) == [
        "-l",
        "line-length=80",
    ]
