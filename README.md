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
      - id: dbt-lint
      - id: dbt-format
```

## `dbt-compile`

Runs `dbt parse` on dbt Fusion, validating the whole project graph: Jinja,
`ref`/`source` resolution, macros, tests and YAML config.

Supported `--adapter` values are `snowflake` (default), `clickhouse` and `duckdb`;
`DBT_CI_ADAPTER` sets it too. Anything else fails fast.

## `dbt-lint` and `dbt-format`

Run Fusion's native `dbt lint` and `dbt format`. Both resolve the project graph
first, so rules see `ref`, `source` and macros expanded rather than raw Jinja, and
neither opens a warehouse connection. No second dbt installation and no templater
are involved — the same `dbt` binary that backs `dbt-compile` does the work.

They are SQLFluff-compatible: rules and layout come from your `.sqlfluff` (the
nearest one, found by walking up the project tree), paths are excluded with
`.sqlfluffignore`, rule codes are unchanged (`CP01`, `LT04`, …) and `-- noqa`
comments are respected.

### `pyproject.toml` config

Fusion reads `.sqlfluff` files only — it ignores `[tool.sqlfluff…]` in
`pyproject.toml`, which stock SQLFluff honoured. The hooks bridge that gap without
putting a `.sqlfluff` in your working tree:

- `dbt-lint` renders the `[tool.sqlfluff…]` tables into a `.sqlfluff` in a temporary
  directory and passes it as `--config`, so the whole config applies.
- `dbt-format` takes no `--config`, so its layout settings are translated into the
  `-l` flags it does accept: `tab_space_size` → `indent`, `max_line_length` →
  `line-length`, `[tool.sqlfluff.layout.type.comma] line_position` → `commas`.

The nearest `pyproject.toml` with a `[tool.sqlfluff]` table wins, found by walking up
from the project directory. An explicit `--config` (or `-l`) in the hook's `args`
takes precedence and disables the translation. A real `.sqlfluff` needs nothing —
Fusion finds it in either the project directory or the repo root.

Fusion warns `SQLFluff templater 'jinja' is not supported` unless a discovered
`.sqlfluff` sets `templater = dbt`; a `--config` file does not silence it. The warning
is cosmetic — Fusion always uses its own dbt templater.

The adapter written into the generated profile decides the SQL dialect, so keep
`--adapter` matching the real warehouse (default `snowflake`).

`dbt-lint` receives the staged SQL files from pre-commit. `dbt-format` rewrites
files in place; because the CLI takes only one file per invocation, the hook runs
once over the **whole project** instead of once per staged file. pre-commit
compares file hashes itself, so it reports a failure the first time formatting
changes anything — review the diff and commit again.

`dbt deps` must have run: linting parses the project, so missing packages fail the
hook.

Useful pass-through flags:

| Flag | Hook | Purpose |
| --- | --- | --- |
| `--fix` | `dbt-lint` | Apply auto-fixable rule violations (one pass). |
| `--rules`, `--exclude-rules` | `dbt-lint` | Comma-separated rule codes, overriding `.sqlfluff`. |
| `--format json\|github-annotation` | `dbt-lint` | Machine-readable violations. |
| `--check` | `dbt-format` | Report unformatted files without writing. |
| `-l line-length=120` | `dbt-format` | Layout overrides (`indent=`, `commas=`, `line-length=`). |

## Options

All three hooks accept:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--project-dir` | `dbt` | Directory containing `dbt_project.yml`. |
| `--adapter` | `$DBT_CI_ADAPTER`, else `snowflake` | Adapter type written into the profile. |
| anything else | — | Forwarded verbatim to `dbt parse` / `dbt lint` / `dbt format`. |

```yaml
      - id: dbt-lint
        args: [--project-dir, transform, --exclude-rules, "LT02,ST06"]
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
