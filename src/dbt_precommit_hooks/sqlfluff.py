"""Run SQLFluff with the dbt templater against a disposable CI profile.

The dbt templater compiles each model through dbt itself, so ``ref``, ``source``
and macros are resolved before any rule runs. It reads its settings from the
consumer's ``.sqlfluff`` first, then falls back to ``DBT_ENGINE_*`` and ``DBT_*``
environment variables, which is how the generated profile and the project
location are handed over -- no config file of ours is written.

Unlike ``dbt parse``, the templater really does open a dbt connection, so a
profile full of unreachable placeholder credentials is not enough -- it fails with
"dbt tried to connect to the database and failed". The generated profile therefore
uses an in-process DuckDB, which connects without a server, credentials or
network. The SQL dialect the rules enforce is unaffected: that comes from the
consumer's ``.sqlfluff``.

Templating through a different adapter than the project really uses does break
``adapter.dispatch`` for packages that ship warehouse specific macros only, so
:mod:`dbt_precommit_hooks.dispatch_shims` stubs those out for the duration of the
run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import nullcontext

from dbt_precommit_hooks.dispatch_shims import dispatch_shims
from dbt_precommit_hooks.profiles import (
    CI_TARGET,
    base_parser,
    ci_profiles_dir,
    read_profile_name,
)

TEMPLATER_ADAPTER = "duckdb"

MISSING_SQLFLUFF = (
    "dbt-precommit-hooks: sqlfluff is not on PATH. This hook needs "
    "sqlfluff-templater-dbt, dbt-core and a dbt adapter in its additional_dependencies."
)


def _run(subcommand: str, argv: list[str] | None) -> int:
    parser = base_parser(
        f"sqlfluff-{subcommand}",
        f"Run 'sqlfluff {subcommand}' with the dbt templater against a disposable CI profile.",
        default_adapter=TEMPLATER_ADAPTER,
    )
    parser.add_argument("paths", nargs="*", help="Files to lint, as passed by pre-commit.")
    args, extra = parser.parse_known_args(argv)
    extra = [item for item in extra if item != "--"]

    if not args.paths:
        return 0

    if shutil.which("sqlfluff") is None:
        raise SystemExit(MISSING_SQLFLUFF)

    # The project is located through DBT_PROJECT_DIR rather than by changing
    # directory, so the repo-root-relative paths pre-commit passes stay valid.
    project_dir = args.project_dir.resolve()
    profile_name = read_profile_name(project_dir / "dbt_project.yml")

    shims = nullcontext([]) if args.no_dispatch_shims else dispatch_shims(project_dir, args.adapter)

    with ci_profiles_dir(profile_name, args.adapter) as profiles_dir, shims:
        return subprocess.call(
            ["sqlfluff", subcommand, "--templater", "dbt", *extra, *args.paths],
            env={
                **os.environ,
                "DBT_PROFILES_DIR": str(profiles_dir),
                "DBT_PROJECT_DIR": str(project_dir),
                "DBT_TARGET": CI_TARGET,
            },
        )


def lint(argv: list[str] | None = None) -> int:
    return _run("lint", argv)


def fix(argv: list[str] | None = None) -> int:
    return _run("fix", argv)
