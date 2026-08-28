"""Lint and format dbt models with dbt Fusion against a disposable CI profile.

``dbt lint`` and ``dbt format`` are native Fusion commands. They resolve the
project graph first -- so ``ref``, ``source`` and macros are expanded before any
rule runs -- which means dbt insists on a profile for the project's adapter, but
nothing connects to a warehouse. :mod:`dbt_precommit_hooks.profiles` generates
that profile.

Rules and layout come from the consumer's ``.sqlfluff`` (auto-discovered by
walking up the project tree) and paths can be excluded with ``.sqlfluffignore``.
Fusion does not read ``[tool.sqlfluff]`` from ``pyproject.toml`` the way stock
SQLFluff did, so :mod:`dbt_precommit_hooks.sqlfluff_config` hands that config
over instead. The adapter written into the generated profile decides the SQL
dialect, so keep ``--adapter`` matching the real warehouse.

``dbt format`` only accepts a single file per invocation, so that hook formats
the whole project in one pass rather than shelling out once per staged file.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from contextlib import nullcontext
from pathlib import Path

from dbt_precommit_hooks.profiles import (
    CI_TARGET,
    base_parser,
    ci_profiles_dir,
    read_profile_name,
)
from dbt_precommit_hooks.sqlfluff_config import (
    find_pyproject,
    layout_flags,
    read_config,
    sqlfluff_config_file,
)


def _parse(prog: str, description: str, argv: list[str] | None):
    parser = base_parser(prog, description)
    args, extra = parser.parse_known_args(argv)
    args.extra = [item for item in extra if item != "--"]
    return args


def _run(command: list[str], args: argparse.Namespace, project_dir: Path) -> int:
    profile_name = read_profile_name(project_dir / "dbt_project.yml")

    with ci_profiles_dir(profile_name, args.adapter) as profiles_dir:
        return subprocess.call(
            command,
            cwd=project_dir,
            env={**os.environ, "DBT_PROFILES_DIR": str(profiles_dir)},
        )


def _split_paths(tokens: list[str], project_dir: Path) -> tuple[list[str], list[str]]:
    """Separate the filenames pre-commit appends from flags meant for ``dbt``.

    Unknown flags may take a value (``--rules CP01``), so the two cannot be told
    apart by position -- a token is a file to lint only if it exists on disk.
    Paths arrive relative to the repo root while the command runs with ``cwd``
    set to the project, so they are re-anchored here; anything outside the
    project cannot be linted and is dropped.
    """
    flags: list[str] = []
    paths: list[str] = []
    for token in tokens:
        candidate = Path(token)
        if not candidate.is_file():
            flags.append(token)
            continue
        try:
            paths.append(str(candidate.resolve().relative_to(project_dir)))
        except ValueError:
            continue
    return flags, paths


def _pyproject_config(project_dir: Path) -> dict:
    """Return the ``[tool.sqlfluff]`` config nearest to the project, or ``{}``."""
    pyproject = find_pyproject(project_dir)
    return read_config(pyproject) if pyproject else {}


def lint(argv: list[str] | None = None) -> int:
    args = _parse("dbt-lint", "Run 'dbt lint' against a disposable CI profile.", argv)
    project_dir = args.project_dir.resolve()
    flags, paths = _split_paths(args.extra, project_dir)
    if not paths:
        return 0

    # An explicit --config wins; otherwise hand over pyproject.toml's config,
    # which Fusion would not find on its own.
    config = {} if "--config" in flags else _pyproject_config(project_dir)
    translated = sqlfluff_config_file(config) if config else nullcontext(None)

    with translated as config_file:
        extra = ["--config", str(config_file)] if config_file else []
        return _run(
            ["dbt", "lint", "--target", CI_TARGET, *extra, *flags, *paths], args, project_dir
        )


def format_(argv: list[str] | None = None) -> int:
    args = _parse(
        "dbt-format",
        "Run 'dbt format' over the whole project against a disposable CI profile.",
        argv,
    )
    project_dir = args.project_dir.resolve()

    # 'dbt format' takes no config file, so pyproject.toml's layout settings are
    # passed as -l flags instead. Explicit -l arguments win.
    explicit_layout = {"-l", "--layout"} & set(args.extra)
    layout = [] if explicit_layout else layout_flags(_pyproject_config(project_dir))

    return _run(["dbt", "format", "--target", CI_TARGET, *layout, *args.extra], args, project_dir)
