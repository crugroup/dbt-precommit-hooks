from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dbt_precommit_hooks import dbt_autofix_check

MISSPELLED_HOOK = {
    "mode": "dry_run",
    "file_path": "{project}/models/mart.yaml",
    "refactors": [
        {
            "deprecation": "CustomKeyInConfigDeprecation",
            "log": "Model 'mart' - Config 'pre-hook' is a common misspelling of 'pre_hook', "
            "it has been renamed.",
        }
    ],
}


def _fake_run(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict],
    returncode: int = 0,
    stderr: str = "",
) -> list[list[str]]:
    """Stand in for dbt-autofix, printing ``records`` as its JSON lines output."""
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=False, text=False):
        calls.append(cmd)
        project_dir = cmd[cmd.index("--path") + 1]
        lines = [
            json.dumps({**r, "file_path": r["file_path"].format(project=project_dir)})
            for r in records
        ]
        lines.append(json.dumps({"mode": "complete"}))
        return subprocess.CompletedProcess(cmd, returncode, "\n".join(lines) + "\n", stderr)

    monkeypatch.setattr(dbt_autofix_check.subprocess, "run", fake_run)
    return calls


def test_main_runs_dbt_autofix_dry_run(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_run(monkeypatch, [])

    assert dbt_autofix_check.main([]) == 0

    assert calls == [
        [
            "dbt-autofix",
            "deprecations",
            "--path",
            str(project.resolve()),
            "--dry-run",
            "--json",
        ]
    ]


def test_main_fails_and_lists_pending_refactors(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_run(monkeypatch, [MISSPELLED_HOOK])

    assert dbt_autofix_check.main([]) == 1

    out = capsys.readouterr().out
    assert "dbt/models/mart.yaml: Model 'mart' - Config 'pre-hook' is a common misspelling" in out
    assert "[CustomKeyInConfigDeprecation]" in out
    assert "dbt-autofix would apply 1 change(s)" in out
    assert "dbt-autofix deprecations --path dbt" in out


def test_main_reports_warnings_without_failing(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_run(
        monkeypatch,
        [
            {
                "mode": "dry_run",
                "file_path": "{project}/models/legacy.sql",
                "refactors": [],
                "warnings": ["Cannot fix automatically"],
            }
        ],
    )

    assert dbt_autofix_check.main([]) == 0
    assert "dbt/models/legacy.sql: warning: Cannot fix automatically" in capsys.readouterr().out


def test_main_ignores_non_json_lines(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dbt_autofix_check.subprocess,
        "run",
        lambda cmd, capture_output=False, text=False: subprocess.CompletedProcess(
            cmd, 0, 'Identifying deprecations\n{"mode": "complete"}\n', ""
        ),
    )

    assert dbt_autofix_check.main([]) == 0


def test_main_propagates_dbt_autofix_failure(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_run(monkeypatch, [MISSPELLED_HOOK], returncode=2, stderr="schema download failed")

    assert dbt_autofix_check.main([]) == 2
    assert "schema download failed" in capsys.readouterr().err


def test_main_forwards_args(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_run(monkeypatch, [])

    dbt_autofix_check.main(["--", "--json-schema-version", "2.0.9", "--behavior-change"])

    assert calls[0][-3:] == ["--json-schema-version", "2.0.9", "--behavior-change"]


def test_main_accepts_explicit_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "transform"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text("profile: other_profile\n", encoding="utf-8")
    calls = _fake_run(monkeypatch, [])

    assert dbt_autofix_check.main(["--project-dir", str(project_dir)]) == 0
    assert calls[0][3] == str(project_dir.resolve())


def test_main_reports_missing_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="not found"):
        dbt_autofix_check.main([])
