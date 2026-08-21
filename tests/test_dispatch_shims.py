from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dbt_precommit_hooks import dispatch_shims


def install(project: Path, package: str, macros: dict[str, str]) -> Path:
    """Write ``{filename: body}`` into an installed package's macros directory."""
    macros_dir = project / "dbt_packages" / package / "macros"
    macros_dir.mkdir(parents=True, exist_ok=True)
    for filename, body in macros.items():
        (macros_dir / filename).write_text(body, encoding="utf-8")
    return macros_dir


def macro(name: str) -> str:
    return f"{{% macro {name}(table, columns, quote_columns=False) %}}select 1{{% endmacro %}}"


def test_adapter_only_macro_is_a_gap(project: Path) -> None:
    macros_dir = install(
        project, "dbt_constraints", {"pk.sql": macro("snowflake__create_primary_key")}
    )

    gaps = dispatch_shims.find_dispatch_gaps(project / "dbt_packages", "duckdb")

    assert gaps == {macros_dir: ["create_primary_key"]}


def test_reachable_macros_are_not_gaps(project: Path) -> None:
    install(
        project,
        "dbt_utils",
        {
            "has_default.sql": macro("default__star") + macro("snowflake__star"),
            "has_duckdb.sql": macro("snowflake__concat") + macro("duckdb__concat"),
        },
    )

    assert dispatch_shims.find_dispatch_gaps(project / "dbt_packages", "duckdb") == {}


def test_unknown_prefixes_are_ignored(project: Path) -> None:
    install(project, "odd", {"m.sql": macro("some_thing__helper") + macro("plain_macro")})

    assert dispatch_shims.find_dispatch_gaps(project / "dbt_packages", "duckdb") == {}


def test_gaps_are_grouped_per_package(project: Path) -> None:
    constraints = install(
        project,
        "dbt_constraints",
        {
            "pk.sql": macro("snowflake__create_primary_key"),
            "uk.sql": macro("snowflake__create_unique_key"),
        },
    )
    other = install(project, "other", {"m.sql": macro("bigquery__cluster_by")})

    gaps = dispatch_shims.find_dispatch_gaps(project / "dbt_packages", "duckdb")

    assert gaps == {
        constraints: ["create_primary_key", "create_unique_key"],
        other: ["cluster_by"],
    }


def test_target_adapter_decides_what_is_missing(project: Path) -> None:
    install(project, "dbt_constraints", {"pk.sql": macro("snowflake__create_primary_key")})

    assert dispatch_shims.find_dispatch_gaps(project / "dbt_packages", "snowflake") == {}


def test_packages_install_path_is_honoured(project: Path) -> None:
    (project / "dbt_project.yml").write_text(
        yaml.safe_dump(
            {
                "name": "demo",
                "profile": "demo_profile",
                "version": "1.0.0",
                "packages-install-path": "vendor",
            }
        ),
        encoding="utf-8",
    )
    macros_dir = project / "vendor" / "dbt_constraints" / "macros"
    macros_dir.mkdir(parents=True)
    (macros_dir / "pk.sql").write_text(macro("snowflake__create_primary_key"), encoding="utf-8")

    with dispatch_shims.dispatch_shims(project, "duckdb") as written:
        assert written == [macros_dir / dispatch_shims.SHIM_FILENAME]


def test_package_macro_paths_are_honoured(project: Path) -> None:
    package = project / "dbt_packages" / "odd_layout"
    (package / "macros").mkdir(parents=True)
    (package / "custom").mkdir()
    (package / "dbt_project.yml").write_text(
        yaml.safe_dump({"name": "odd_layout", "macro-paths": ["custom"]}), encoding="utf-8"
    )
    (package / "custom" / "pk.sql").write_text(
        macro("snowflake__create_primary_key"), encoding="utf-8"
    )

    gaps = dispatch_shims.find_dispatch_gaps(project / "dbt_packages", "duckdb")

    assert gaps == {package / "custom": ["create_primary_key"]}


def test_missing_packages_dir_is_a_no_op(project: Path) -> None:
    with dispatch_shims.dispatch_shims(project, "duckdb") as written:
        assert written == []


def test_shim_file_is_written_and_removed(project: Path) -> None:
    macros_dir = install(
        project, "dbt_constraints", {"pk.sql": macro("snowflake__create_primary_key")}
    )
    shim_file = macros_dir / dispatch_shims.SHIM_FILENAME

    with dispatch_shims.dispatch_shims(project, "duckdb") as written:
        assert written == [shim_file]
        assert "{% macro duckdb__create_primary_key() %}" in shim_file.read_text(encoding="utf-8")

    assert not shim_file.exists()


def test_shims_survive_a_failing_run(project: Path) -> None:
    macros_dir = install(
        project, "dbt_constraints", {"pk.sql": macro("snowflake__create_primary_key")}
    )
    shim_file = macros_dir / dispatch_shims.SHIM_FILENAME

    with pytest.raises(RuntimeError), dispatch_shims.dispatch_shims(project, "duckdb"):
        raise RuntimeError("sqlfluff blew up")

    assert not shim_file.exists()


def test_existing_shim_file_is_left_alone(project: Path) -> None:
    macros_dir = install(
        project, "dbt_constraints", {"pk.sql": macro("snowflake__create_primary_key")}
    )
    shim_file = macros_dir / dispatch_shims.SHIM_FILENAME
    shim_file.write_text("-- from a killed run\n", encoding="utf-8")

    with dispatch_shims.dispatch_shims(project, "duckdb") as written:
        assert written == []

    assert shim_file.read_text(encoding="utf-8") == "-- from a killed run\n"


def test_stub_accepts_any_signature() -> None:
    """The stubs declare no arguments, so Jinja must collect them as varargs."""
    jinja2 = pytest.importorskip("jinja2")
    env = jinja2.Environment()
    env.globals["return"] = lambda value: value

    template = env.from_string(
        dispatch_shims.render_shims(["create_primary_key"], "duckdb")
        + "{{ duckdb__create_primary_key('t', ['a', 'b'], quote_columns=True) }}"
    )

    assert template.render().strip() == ""
