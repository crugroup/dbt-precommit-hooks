# dbt-precommit-hooks

Shared [pre-commit](https://pre-commit.com/) hooks for dbt projects.

Each hook writes a throwaway `profiles.yml` to a temporary directory, points dbt
at it, and deletes it afterwards — no warehouse, no credentials. The profile name
comes from `profile:` in `dbt_project.yml`, the target is always `ci`, and the
project is expected in `dbt/` (`--project-dir` to change it).

```yaml
repos:
  - repo: https://github.com/crugroup/dbt-precommit-hooks
    rev: v0.1.0
    hooks:
      - id: dbt-compile
      - id: sqlfluff-lint
      - id: sqlfluff-fix
```

## `dbt-compile`

Runs `dbt parse` on dbt Fusion, validating the whole project graph: Jinja,
`ref`/`source` resolution, macros, tests and YAML config.

Supported `--adapter` values are `snowflake` (default), `clickhouse` and `duckdb`;
`DBT_CI_ADAPTER` sets it too. Anything else fails fast.

## `sqlfluff-lint` and `sqlfluff-fix`

Run SQLFluff with the **dbt templater**, so rules see compiled SQL rather than raw
Jinja. `sqlfluff-fix` rewrites files in place, so pre-commit reports a failure the
first time it changes something — review the diff and commit again.

Unlike `dbt parse`, the templater really connects, so these hooks default to an
in-process DuckDB profile (`path: ':memory:'`) that needs no server. Only dbt's
templating uses it; the dialect the rules enforce comes from your `.sqlfluff`, so
Snowflake and ClickHouse projects are linted as Snowflake and ClickHouse SQL.
Adapter-dispatched macros (`snowflake__…`, `clickhouse__…`) do fall back to their
`default__` variant while linting — use `--adapter` with a reachable warehouse if
you need exact fidelity.

Models that query at compile time (`run_query`, `dbt_utils.get_column_values`)
can't be templated against an empty database. Exclude them with `.sqlfluffignore`,
or set `dbt_skip_compilation_error = True` under `[sqlfluff:templater:dbt]`.

SQLFluff's dbt templater imports dbt Core internals that Fusion does not expose
([dbt-fusion#11](https://github.com/dbt-labs/dbt-fusion/issues/11)), so these
hooks pin dbt Core 1.x. pre-commit gives every hook its own virtualenv, so
`dbt-compile` keeps running Fusion regardless:

```yaml
  - sqlfluff-templater-dbt==4.3.0
  - dbt-core~=1.12.0
  - dbt-duckdb~=1.11.0
```

Overriding `additional_dependencies` *replaces* that list, so restate all of it
when swapping the adapter.

## Options

Both hooks accept:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--project-dir` | `dbt` | Directory containing `dbt_project.yml`. |
| `--adapter` | `$DBT_CI_ADAPTER`, else `snowflake` (`duckdb` for the sqlfluff hooks) | Adapter type written into the profile. |
| anything else | — | Forwarded verbatim to `dbt parse` / `sqlfluff`. |

```yaml
      - id: sqlfluff-lint
        args: [--project-dir, transform, --dialect, snowflake]
```

## Development

```bash
uv sync
uv run pytest
uv run pre-commit run --all-files
```

Tag releases so consumers can pin `rev:`:

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```
