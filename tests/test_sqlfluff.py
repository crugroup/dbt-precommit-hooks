from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dbt_precommit_hooks import sqlfluff


@pytest.fixture(autouse=True)
def sqlfluff_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlfluff.shutil, "which", lambda name: f"/usr/bin/{name}")


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_call(cmd, env=None, **kwargs):
        calls.append({"cmd": cmd, "env": env, "kwargs": kwargs})
        return 0

    monkeypatch.setattr(sqlfluff.subprocess, "call", fake_call)
    return calls


def test_lint_builds_command(project: Path, recorder: list[dict]) -> None:
    assert sqlfluff.lint(["dbt/models/a.sql", "dbt/models/b.sql"]) == 0

    (call,) = recorder
    assert call["cmd"] == [
        "sqlfluff",
        "lint",
        "--templater",
        "dbt",
        "dbt/models/a.sql",
        "dbt/models/b.sql",
    ]
    # The working directory is left alone so pre-commit's relative paths resolve.
    assert call["kwargs"] == {}


def test_fix_builds_command(project: Path, recorder: list[dict]) -> None:
    assert sqlfluff.fix(["dbt/models/a.sql"]) == 0

    assert recorder[0]["cmd"][:4] == ["sqlfluff", "fix", "--templater", "dbt"]


def test_env_points_dbt_at_generated_profile(project: Path, recorder: list[dict]) -> None:
    sqlfluff.lint(["dbt/models/a.sql"])

    env = recorder[0]["env"]
    profiles_dir = Path(env["DBT_PROFILES_DIR"])
    assert env["DBT_PROJECT_DIR"] == str(project.resolve())
    assert env["DBT_TARGET"] == "ci"

    # Written and removed inside the subprocess call, so read it from the recorder.
    assert not profiles_dir.exists()


def test_profile_is_readable_during_the_call(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict] = []

    def fake_call(cmd, env=None, **kwargs):
        seen.append(yaml.safe_load(Path(env["DBT_PROFILES_DIR"], "profiles.yml").read_text()))
        return 0

    monkeypatch.setattr(sqlfluff.subprocess, "call", fake_call)

    sqlfluff.lint(["dbt/models/a.sql"])

    output = seen[0]["demo_profile"]["outputs"]["ci"]
    assert output["type"] == "duckdb"
    assert output["path"] == ":memory:"


def test_extra_flags_precede_filenames(project: Path, recorder: list[dict]) -> None:
    sqlfluff.lint(["--dialect", "snowflake", "dbt/models/a.sql"])

    assert recorder[0]["cmd"] == [
        "sqlfluff",
        "lint",
        "--templater",
        "dbt",
        "--dialect",
        "snowflake",
        "dbt/models/a.sql",
    ]


def test_adapter_selection(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapters: list[str] = []

    def fake_call(cmd, env=None, **kwargs):
        profile = yaml.safe_load(Path(env["DBT_PROFILES_DIR"], "profiles.yml").read_text())
        adapters.append(profile["demo_profile"]["outputs"]["ci"]["type"])
        return 0

    monkeypatch.setattr(sqlfluff.subprocess, "call", fake_call)
    monkeypatch.setenv("DBT_CI_ADAPTER", "clickhouse")

    sqlfluff.lint(["dbt/models/a.sql"])
    sqlfluff.lint(["--adapter", "snowflake", "dbt/models/a.sql"])

    assert adapters == ["clickhouse", "snowflake"]


def test_default_adapter_is_duckdb(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The templater opens a real connection, so the default must be embedded."""
    adapters: list[str] = []

    def fake_call(cmd, env=None, **kwargs):
        profile = yaml.safe_load(Path(env["DBT_PROFILES_DIR"], "profiles.yml").read_text())
        adapters.append(profile["demo_profile"]["outputs"]["ci"]["type"])
        return 0

    monkeypatch.delenv("DBT_CI_ADAPTER", raising=False)
    monkeypatch.setattr(sqlfluff.subprocess, "call", fake_call)

    sqlfluff.lint(["dbt/models/a.sql"])

    assert adapters == ["duckdb"]


def test_explicit_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "transform"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text("profile: other_profile\n", encoding="utf-8")

    seen: list[str] = []
    monkeypatch.setattr(
        sqlfluff.subprocess,
        "call",
        lambda cmd, env=None, **kwargs: seen.append(env["DBT_PROJECT_DIR"]) or 0,
    )

    assert sqlfluff.lint(["--project-dir", str(project_dir), "transform/models/a.sql"]) == 0
    assert seen == [str(project_dir.resolve())]


def test_no_filenames_is_a_no_op(project: Path, recorder: list[dict]) -> None:
    assert sqlfluff.lint([]) == 0
    assert recorder == []


def test_missing_sqlfluff_is_reported(
    project: Path, recorder: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlfluff.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit, match="additional_dependencies"):
        sqlfluff.lint(["dbt/models/a.sql"])

    assert recorder == []


def test_exit_code_is_propagated(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlfluff.subprocess, "call", lambda cmd, env=None, **kwargs: 65)

    assert sqlfluff.lint(["dbt/models/a.sql"]) == 65


def test_missing_project_file_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="not found"):
        sqlfluff.lint(["models/a.sql"])
