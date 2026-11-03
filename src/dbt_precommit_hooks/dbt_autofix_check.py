"""Fail when dbt-autofix would rewrite the project.

``dbt-autofix deprecations`` (dbt Labs) knows the spellings dbt Fusion expects --
``pre_hook`` in a model's YAML or SQL ``config()``, ``+pre-hook`` in
``dbt_project.yml`` -- and rewrites files that drift from them. dbt Fusion
accepts several of these drifts silently, so ``dbt parse`` does not catch them,
while dbt Core treats them as unknown keys. This hook runs dbt-autofix in
dry-run mode and fails, listing each pending refactor, so the drift is fixed
before it is committed. Nothing is written.

dbt-autofix reads files only, so no profile is generated. It does download the
dbt Fusion JSON schemas from ``public.cdn.getdbt.com`` on every run, so the hook
needs network access.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dbt_precommit_hooks.profiles import DEFAULT_PROJECT_DIR, read_project


def _records(stdout: str) -> Iterator[dict[str, Any]]:
    """Yield the per-file records of ``dbt-autofix --json`` output (one JSON object per line)."""
    for line in stdout.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and "file_path" in record:
            yield record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dbt-autofix-check",
        description="Fail when dbt-autofix would rewrite the dbt project.",
        epilog="Any other argument is forwarded verbatim to `dbt-autofix deprecations`.",
    )
    parser.add_argument(
        "--project-dir",
        default=DEFAULT_PROJECT_DIR,
        type=Path,
        help=f"Directory containing dbt_project.yml (default: {DEFAULT_PROJECT_DIR}).",
    )
    args, extra = parser.parse_known_args(argv)
    extra = [item for item in extra if item != "--"]

    project_dir = args.project_dir.resolve()
    read_project(project_dir / "dbt_project.yml")

    result = subprocess.run(
        ["dbt-autofix", "deprecations", "--path", str(project_dir), "--dry-run", "--json", *extra],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    pending = 0
    for record in _records(result.stdout):
        path = os.path.relpath(record["file_path"])
        for refactor in record.get("refactors", []):
            print(f"{path}: {refactor['log']} [{refactor['deprecation']}]")
            pending += 1
        for warning in record.get("warnings", []):
            print(f"{path}: warning: {warning}")

    if pending:
        print(
            f"\ndbt-autofix would apply {pending} change(s). Apply them with:\n"
            f"  dbt-autofix deprecations --path {os.path.relpath(project_dir)}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
