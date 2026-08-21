from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dbt_precommit_hooks import profiles


def test_read_profile_name(project: Path) -> None:
    assert profiles.read_profile_name(project / "dbt_project.yml") == "demo_profile"


def test_read_profile_name_missing_project_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not found"):
        profiles.read_profile_name(tmp_path / "dbt_project.yml")


def test_read_profile_name_missing_profile_key(tmp_path: Path) -> None:
    project_file = tmp_path / "dbt_project.yml"
    project_file.write_text("name: demo\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="does not declare a 'profile' key"):
        profiles.read_profile_name(project_file)


def test_build_profile_snowflake() -> None:
    profile = profiles.build_profile("demo_profile", "snowflake")
    output = profile["demo_profile"]["outputs"]["ci"]

    assert profile["demo_profile"]["target"] == "ci"
    assert output["type"] == "snowflake"
    assert output["account"] == "ci"


def test_build_profile_clickhouse() -> None:
    output = profiles.build_profile("demo_profile", "clickhouse")["demo_profile"]["outputs"]["ci"]

    assert output["type"] == "clickhouse"
    assert output["host"] == "localhost"
    assert output["port"] == 8123


def test_build_profile_rejects_unknown_adapter() -> None:
    with pytest.raises(SystemExit, match="unsupported adapter 'postgres'"):
        profiles.build_profile("demo_profile", "postgres")


def test_ci_profiles_dir_writes_and_cleans_up() -> None:
    with profiles.ci_profiles_dir("demo_profile", "snowflake") as profiles_dir:
        written = yaml.safe_load((profiles_dir / "profiles.yml").read_text(encoding="utf-8"))
        assert written == profiles.build_profile("demo_profile", "snowflake")

    assert not profiles_dir.exists()


def test_base_parser_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DBT_CI_ADAPTER", raising=False)
    args = profiles.base_parser("demo", "demo").parse_args([])

    assert args.project_dir == Path("dbt")
    assert args.adapter == "snowflake"


def test_base_parser_adapter_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBT_CI_ADAPTER", "clickhouse")

    assert profiles.base_parser("demo", "demo").parse_args([]).adapter == "clickhouse"
