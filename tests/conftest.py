from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo root containing a dbt project in the default ``dbt/`` directory."""
    project_dir = tmp_path / "dbt"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text(
        yaml.safe_dump({"name": "demo", "profile": "demo_profile", "version": "1.0.0"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return project_dir
