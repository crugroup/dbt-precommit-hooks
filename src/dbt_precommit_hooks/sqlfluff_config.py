"""Feed ``[tool.sqlfluff]`` config from ``pyproject.toml`` to dbt Fusion.

Stock SQLFluff read its settings from ``pyproject.toml``, ``setup.cfg`` and
``tox.ini`` as well as ``.sqlfluff``. Fusion's ``dbt lint`` / ``dbt format`` read
``.sqlfluff`` only, so a project keeping its rules in ``pyproject.toml`` silently
lints with defaults.

Rather than write a ``.sqlfluff`` into the working tree, the helpers here render
the ``[tool.sqlfluff…]`` tables into a ``.sqlfluff`` in a temporary directory:

* ``dbt lint`` takes it via ``--config``, which overrides Fusion's own discovery.
* ``dbt format`` has no ``--config``, but the layout keys it honours are exactly
  the three its ``-l/--layout`` flag exposes, so those are passed instead.
"""

from __future__ import annotations

import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# ``.sqlfluff`` section names are ``:``-joined, so nested TOML tables map onto
# them directly -- except ``core``, which is the top-level ``[sqlfluff]``.
CORE_SECTION = "core"


def find_pyproject(start: Path) -> Path | None:
    """Return the nearest ``pyproject.toml`` holding ``[tool.sqlfluff]``.

    Walks up from ``start``, the same way Fusion looks for a ``.sqlfluff``.
    """
    for directory in [start, *start.parents]:
        candidate = directory / "pyproject.toml"
        if candidate.is_file() and read_config(candidate):
            return candidate
    return None


def read_config(pyproject: Path) -> dict[str, Any]:
    """Return the ``[tool.sqlfluff]`` table of ``pyproject``, or ``{}``."""
    with pyproject.open("rb") as handle:
        try:
            parsed = tomllib.load(handle)
        except tomllib.TOMLDecodeError as error:
            raise SystemExit(f"dbt-precommit-hooks: cannot parse {pyproject}: {error}") from error

    return parsed.get("tool", {}).get("sqlfluff", {})


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list | tuple):
        return ",".join(str(item) for item in value)
    return str(value)


def render_sqlfluff(config: dict[str, Any], prefix: str = "sqlfluff") -> str:
    """Render a ``[tool.sqlfluff]`` table as ``.sqlfluff`` INI text."""
    values = {key: value for key, value in config.items() if not isinstance(value, dict)}
    tables = {key: value for key, value in config.items() if isinstance(value, dict)}

    sections: list[str] = []
    if values:
        body = "".join(f"{key} = {_format_value(value)}\n" for key, value in values.items())
        sections.append(f"[{prefix}]\n{body}")

    # ``[tool.sqlfluff.core]`` is the top-level ``[sqlfluff]`` section, so it is
    # rendered under the current prefix rather than as a child of it.
    for key, table in tables.items():
        child = prefix if key == CORE_SECTION and prefix == "sqlfluff" else f"{prefix}:{key}"
        sections.append(render_sqlfluff(table, child))

    return "".join(sections)


@contextmanager
def sqlfluff_config_file(config: dict[str, Any]) -> Iterator[Path]:
    """Yield a temporary ``.sqlfluff`` rendered from ``config``."""
    with tempfile.TemporaryDirectory(prefix="dbt-precommit-sqlfluff-") as directory:
        path = Path(directory, ".sqlfluff")
        path.write_text(render_sqlfluff(config), encoding="utf-8")
        yield path


def layout_flags(config: dict[str, Any]) -> list[str]:
    """Translate the layout subset of ``config`` into ``dbt format -l`` flags.

    ``dbt format`` takes no config file, and these three knobs are all it
    exposes: ``indent``, ``line-length`` and ``commas``.
    """
    core = {**config, **config.get(CORE_SECTION, {})}
    indentation = config.get("indentation", {})
    comma = config.get("layout", {}).get("type", {}).get("comma", {})

    options = {
        "indent": indentation.get("tab_space_size"),
        "line-length": core.get("max_line_length"),
        "commas": comma.get("line_position"),
    }

    flags: list[str] = []
    for name, value in options.items():
        if value is not None:
            flags += ["-l", f"{name}={_format_value(value)}"]
    return flags
