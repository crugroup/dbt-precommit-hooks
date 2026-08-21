"""Throwaway dbt profiles for hooks that must not touch a warehouse.

Both ``dbt parse`` and SQLFluff's dbt templater refuse to run without a valid
profile for the project's adapter, which is exactly what CI machines and
developer laptops tend not to have. The helpers here generate one with
placeholder credentials in a temporary directory. Nothing connects, so the
values only need to satisfy the profile schema for that adapter type.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

CI_TARGET = "ci"
DEFAULT_ADAPTER = "snowflake"
DEFAULT_PROJECT_DIR = "dbt"

ADAPTER_OUTPUTS: dict[str, dict[str, Any]] = {
    # An in-process DuckDB is the only adapter that can satisfy a hook which
    # really does open a connection (SQLFluff's dbt templater does). It needs no
    # server, no credentials and no network.
    "duckdb": {
        "path": ":memory:",
        "schema": "main",
    },
    "snowflake": {
        "account": "ci",
        "user": "ci",
        "password": "ci",
        "role": "ci",
        "database": "ci",
        "warehouse": "ci",
        "schema": "ci",
    },
    "clickhouse": {
        "host": "localhost",
        "port": 8123,
        "user": "ci",
        "password": "ci",
        "schema": "ci",
        "secure": False,
    },
}


def build_profile(profile_name: str, adapter: str) -> dict[str, Any]:
    """Return a single-target profiles.yml body with placeholder credentials."""
    if adapter not in ADAPTER_OUTPUTS:
        supported = ", ".join(sorted(ADAPTER_OUTPUTS))
        raise SystemExit(
            f"dbt-precommit-hooks: unsupported adapter {adapter!r} (supported: {supported})"
        )

    return {
        profile_name: {
            "target": CI_TARGET,
            "outputs": {CI_TARGET: {"type": adapter, "threads": 1, **ADAPTER_OUTPUTS[adapter]}},
        }
    }


def read_profile_name(project_file: Path) -> str:
    """Read the ``profile`` key out of ``dbt_project.yml``."""
    if not project_file.is_file():
        raise SystemExit(f"dbt-precommit-hooks: {project_file} not found")

    project = yaml.safe_load(project_file.read_text(encoding="utf-8")) or {}
    profile_name = project.get("profile")
    if not profile_name:
        raise SystemExit(f"dbt-precommit-hooks: {project_file} does not declare a 'profile' key")
    return str(profile_name)


@contextmanager
def ci_profiles_dir(profile_name: str, adapter: str) -> Iterator[Path]:
    """Yield a temporary directory holding a generated ``profiles.yml``."""
    with tempfile.TemporaryDirectory(prefix="dbt-precommit-") as profiles_dir:
        Path(profiles_dir, "profiles.yml").write_text(
            yaml.safe_dump(build_profile(profile_name, adapter), sort_keys=False),
            encoding="utf-8",
        )
        yield Path(profiles_dir)


def base_parser(
    prog: str, description: str, default_adapter: str = DEFAULT_ADAPTER
) -> argparse.ArgumentParser:
    """Return a parser with the options every hook in this repo accepts."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=description,
        epilog="Any other argument is forwarded verbatim to the underlying command.",
    )
    parser.add_argument(
        "--project-dir",
        default=DEFAULT_PROJECT_DIR,
        type=Path,
        help=f"Directory containing dbt_project.yml (default: {DEFAULT_PROJECT_DIR}).",
    )
    parser.add_argument(
        "--adapter",
        default=os.environ.get("DBT_CI_ADAPTER", default_adapter),
        choices=sorted(ADAPTER_OUTPUTS),
        help=f"Adapter type for the generated profile (default: {default_adapter}).",
    )
    return parser
