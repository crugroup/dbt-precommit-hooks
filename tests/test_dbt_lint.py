from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dbt_precommit_hooks import dbt_lint


def write_sql(repo_root: Path, *relative: str) -> list[str]:
    """Create SQL files under ``repo_root`` and return their repo-relative paths."""
    for path in relative:
        target = repo_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("select 1\n", encoding="utf-8")
    return list(relative)


def test_lint_runs_dbt_lint_with_generated_profile(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = write_sql(project.parent, "dbt/models/a.sql")
    calls: list[dict] = []

    def fake_call(cmd, cwd=None, env=None):
        profiles_dir = Path(env["DBT_PROFILES_DIR"])
        calls.append(
            {
                "cmd": cmd,
                "cwd": cwd,
                "profiles_dir": profiles_dir,
                "profile": yaml.safe_load((profiles_dir / "profiles.yml").read_text()),
            }
        )
        return 0

    monkeypatch.setattr(dbt_lint.subprocess, "call", fake_call)

    assert dbt_lint.lint(paths) == 0

    (call,) = calls
    assert call["cmd"] == ["dbt", "lint", "--target", "ci", "models/a.sql"]
    assert call["cwd"] == project.resolve()
    assert call["profile"]["demo_profile"]["outputs"]["ci"]["type"] == "snowflake"
    assert not call["profiles_dir"].exists()


def test_lint_reanchors_paths_onto_the_project_dir(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = write_sql(project.parent, "dbt/models/a.sql", "dbt/models/staging/b.sql")
    recorded: list[list[str]] = []
    monkeypatch.setattr(
        dbt_lint.subprocess, "call", lambda cmd, cwd=None, env=None: recorded.append(cmd) or 0
    )

    dbt_lint.lint(paths)

    assert recorded == [["dbt", "lint", "--target", "ci", "models/a.sql", "models/staging/b.sql"]]


def test_lint_drops_paths_outside_the_project(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside, inside = write_sql(project.parent, "scripts/backfill.sql", "dbt/models/a.sql")
    recorded: list[list[str]] = []
    monkeypatch.setattr(
        dbt_lint.subprocess, "call", lambda cmd, cwd=None, env=None: recorded.append(cmd) or 0
    )

    assert dbt_lint.lint([outside]) == 0
    assert recorded == []

    assert dbt_lint.lint([outside, inside]) == 0
    assert recorded == [["dbt", "lint", "--target", "ci", "models/a.sql"]]


def test_lint_without_paths_is_a_no_op(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("dbt should not be invoked without paths")

    monkeypatch.setattr(dbt_lint.subprocess, "call", fail)

    assert dbt_lint.lint([]) == 0


def test_lint_forwards_args_and_exit_code(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = write_sql(project.parent, "dbt/models/a.sql")
    recorded: list[list[str]] = []
    monkeypatch.setattr(
        dbt_lint.subprocess, "call", lambda cmd, cwd=None, env=None: recorded.append(cmd) or 1
    )

    assert dbt_lint.lint(["--rules", "CP01", "--", *paths]) == 1
    assert recorded == [["dbt", "lint", "--target", "ci", "--rules", "CP01", "models/a.sql"]]


PYPROJECT_SQLFLUFF = """
[tool.sqlfluff.core]
dialect = "snowflake"
exclude_rules = ["CP01"]
max_line_length = 30

[tool.sqlfluff.indentation]
tab_space_size = 8
"""


def test_lint_hands_pyproject_config_to_dbt(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fusion does not read pyproject.toml, so the hook renders it and passes --config."""
    paths = write_sql(project.parent, "dbt/models/a.sql")
    (project.parent / "pyproject.toml").write_text(PYPROJECT_SQLFLUFF, encoding="utf-8")

    recorded: list[tuple[list[str], str]] = []

    def fake_call(cmd, cwd=None, env=None):
        config = Path(cmd[cmd.index("--config") + 1])
        recorded.append((cmd, config.read_text(encoding="utf-8")))
        return 0

    monkeypatch.setattr(dbt_lint.subprocess, "call", fake_call)

    assert dbt_lint.lint(paths) == 0

    (cmd, rendered) = recorded[0]
    config_file = Path(cmd[cmd.index("--config") + 1])
    assert cmd[:4] == ["dbt", "lint", "--target", "ci"]
    assert cmd[-1] == "models/a.sql"
    assert "exclude_rules = CP01\n" in rendered
    assert "[sqlfluff:indentation]\ntab_space_size = 8\n" in rendered
    # The rendered config lives in a temp dir, never in the working tree.
    assert not config_file.exists()
    assert not (project.parent / ".sqlfluff").exists()
    assert not (project / ".sqlfluff").exists()


def test_lint_keeps_an_explicit_config_flag(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = write_sql(project.parent, "dbt/models/a.sql")
    (project.parent / "pyproject.toml").write_text(PYPROJECT_SQLFLUFF, encoding="utf-8")

    recorded: list[list[str]] = []
    monkeypatch.setattr(
        dbt_lint.subprocess, "call", lambda cmd, cwd=None, env=None: recorded.append(cmd) or 0
    )

    dbt_lint.lint(["--config", "custom.sqlfluff", *paths])

    assert recorded == [
        ["dbt", "lint", "--target", "ci", "--config", "custom.sqlfluff", "models/a.sql"]
    ]


def test_lint_without_pyproject_config_passes_no_config(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = write_sql(project.parent, "dbt/models/a.sql")
    (project.parent / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")

    recorded: list[list[str]] = []
    monkeypatch.setattr(
        dbt_lint.subprocess, "call", lambda cmd, cwd=None, env=None: recorded.append(cmd) or 0
    )

    dbt_lint.lint(paths)

    assert recorded == [["dbt", "lint", "--target", "ci", "models/a.sql"]]


def test_format_translates_pyproject_layout_to_flags(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """'dbt format' takes no --config, so layout settings become -l flags."""
    (project.parent / "pyproject.toml").write_text(PYPROJECT_SQLFLUFF, encoding="utf-8")

    recorded: list[list[str]] = []
    monkeypatch.setattr(
        dbt_lint.subprocess, "call", lambda cmd, cwd=None, env=None: recorded.append(cmd) or 0
    )

    dbt_lint.format_([])

    assert recorded == [
        [
            "dbt",
            "format",
            "--target",
            "ci",
            "-l",
            "indent=8",
            "-l",
            "line-length=30",
        ]
    ]


def test_format_keeps_explicit_layout_flags(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (project.parent / "pyproject.toml").write_text(PYPROJECT_SQLFLUFF, encoding="utf-8")

    recorded: list[list[str]] = []
    monkeypatch.setattr(
        dbt_lint.subprocess, "call", lambda cmd, cwd=None, env=None: recorded.append(cmd) or 0
    )

    dbt_lint.format_(["-l", "indent=2"])

    assert recorded == [["dbt", "format", "--target", "ci", "-l", "indent=2"]]


def test_lint_accepts_explicit_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "transform"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text("profile: other_profile\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    paths = write_sql(tmp_path, "transform/models/a.sql")

    calls: list[dict] = []
    monkeypatch.setattr(
        dbt_lint.subprocess,
        "call",
        lambda cmd, cwd=None, env=None: calls.append({"cmd": cmd, "cwd": cwd}) or 0,
    )

    assert dbt_lint.lint(["--project-dir", "transform", *paths]) == 0
    assert calls == [
        {"cmd": ["dbt", "lint", "--target", "ci", "models/a.sql"], "cwd": project_dir.resolve()}
    ]


def test_lint_reports_missing_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    paths = write_sql(tmp_path, "dbt/models/a.sql")

    with pytest.raises(SystemExit, match="not found"):
        dbt_lint.lint(paths)


def test_format_runs_over_the_whole_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_call(cmd, cwd=None, env=None):
        profiles_dir = Path(env["DBT_PROFILES_DIR"])
        calls.append(
            {
                "cmd": cmd,
                "cwd": cwd,
                "profile": yaml.safe_load((profiles_dir / "profiles.yml").read_text()),
            }
        )
        return 0

    monkeypatch.setattr(dbt_lint.subprocess, "call", fake_call)

    assert dbt_lint.format_([]) == 0

    (call,) = calls
    assert call["cmd"] == ["dbt", "format", "--target", "ci"]
    assert call["cwd"] == project.resolve()
    assert call["profile"]["demo_profile"]["outputs"]["ci"]["type"] == "snowflake"


def test_format_forwards_args_and_exit_code(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []
    monkeypatch.setattr(
        dbt_lint.subprocess, "call", lambda cmd, cwd=None, env=None: recorded.append(cmd) or 1
    )

    assert dbt_lint.format_(["--check", "-l", "line-length=120"]) == 1
    assert recorded == [["dbt", "format", "--target", "ci", "--check", "-l", "line-length=120"]]


def test_honours_adapter_selection(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = write_sql(project.parent, "dbt/models/a.sql")
    adapters: list[str] = []

    def fake_call(cmd, cwd=None, env=None):
        profile = yaml.safe_load(Path(env["DBT_PROFILES_DIR"], "profiles.yml").read_text())
        adapters.append(profile["demo_profile"]["outputs"]["ci"]["type"])
        return 0

    monkeypatch.setenv("DBT_CI_ADAPTER", "clickhouse")
    monkeypatch.setattr(dbt_lint.subprocess, "call", fake_call)

    dbt_lint.lint(paths)
    dbt_lint.format_(["--adapter", "duckdb"])

    assert adapters == ["clickhouse", "duckdb"]


def test_rejects_unknown_adapter(project: Path) -> None:
    paths = write_sql(project.parent, "dbt/models/a.sql")

    with pytest.raises(SystemExit):
        dbt_lint.lint(["--adapter", "postgres", *paths])
