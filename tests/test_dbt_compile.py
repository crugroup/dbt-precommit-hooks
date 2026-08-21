from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dbt_precommit_hooks import dbt_compile


def test_main_runs_dbt_parse_with_generated_profile(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    monkeypatch.setattr(dbt_compile.subprocess, "call", fake_call)

    assert dbt_compile.main([]) == 0

    (call,) = calls
    assert call["cmd"] == ["dbt", "parse", "--target", "ci"]
    assert call["cwd"] == project.resolve()
    assert call["profile"]["demo_profile"]["outputs"]["ci"]["type"] == "snowflake"
    assert not call["profiles_dir"].exists()


def test_main_accepts_explicit_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "transform"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text("profile: other_profile\n", encoding="utf-8")

    seen: list[Path] = []
    monkeypatch.setattr(
        dbt_compile.subprocess, "call", lambda cmd, cwd=None, env=None: seen.append(cwd) or 0
    )

    assert dbt_compile.main(["--project-dir", str(project_dir)]) == 0
    assert seen == [project_dir.resolve()]


def test_main_reports_missing_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="not found"):
        dbt_compile.main([])


def test_main_forwards_args_and_exit_code(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []
    monkeypatch.setattr(
        dbt_compile.subprocess, "call", lambda cmd, cwd=None, env=None: recorded.append(cmd) or 1
    )

    assert dbt_compile.main(["--no-partial-parse"]) == 1
    assert recorded == [["dbt", "parse", "--target", "ci", "--no-partial-parse"]]


def test_main_honours_adapter_selection(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapters: list[str] = []

    def fake_call(cmd, cwd=None, env=None):
        profile = yaml.safe_load(Path(env["DBT_PROFILES_DIR"], "profiles.yml").read_text())
        adapters.append(profile["demo_profile"]["outputs"]["ci"]["type"])
        return 0

    monkeypatch.setenv("DBT_CI_ADAPTER", "clickhouse")
    monkeypatch.setattr(dbt_compile.subprocess, "call", fake_call)

    dbt_compile.main([])
    dbt_compile.main(["--adapter", "snowflake"])

    assert adapters == ["clickhouse", "snowflake"]


def test_main_rejects_unknown_adapter(project: Path) -> None:
    with pytest.raises(SystemExit):
        dbt_compile.main(["--adapter", "postgres"])
