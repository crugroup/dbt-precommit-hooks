"""Parse a dbt project against a disposable CI profile.

``dbt parse`` resolves the whole project graph -- Jinja, refs, sources, macros,
tests and YAML config -- without touching the warehouse. It still requires a
valid profile, which :mod:`dbt_precommit_hooks.profiles` generates.
"""

from __future__ import annotations

import os
import subprocess

from dbt_precommit_hooks.profiles import (
    CI_TARGET,
    base_parser,
    ci_profiles_dir,
    read_profile_name,
)


def main(argv: list[str] | None = None) -> int:
    parser = base_parser("dbt-compile", "Parse a dbt project against a disposable CI profile.")
    args, dbt_args = parser.parse_known_args(argv)
    dbt_args = [item for item in dbt_args if item != "--"]

    project_dir = args.project_dir.resolve()
    profile_name = read_profile_name(project_dir / "dbt_project.yml")

    with ci_profiles_dir(profile_name, args.adapter) as profiles_dir:
        return subprocess.call(
            ["dbt", "parse", "--target", CI_TARGET, *dbt_args],
            cwd=project_dir,
            env={**os.environ, "DBT_PROFILES_DIR": str(profiles_dir)},
        )


if __name__ == "__main__":
    raise SystemExit(main())
