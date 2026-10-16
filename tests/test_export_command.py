"""Tests for the ``export`` command (persist parsed usage to SQLite)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentcost.persistence import CostPersistence  # noqa: E402
from agentcost.cli import cli  # noqa: E402


def _claude_log(log_dir: Path, model: str, ts: str) -> Path:
    """Write a single-entry Claude JSONL log and return its path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "model": model,
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        },
    }
    path = log_dir / f"claude_{model.replace('/', '_')}.jsonl"
    path.write_text(json.dumps(entry) + "\n")
    return path


def test_export_writes_to_sqlite(tmp_path: Path):
    log = _claude_log(tmp_path / "logs", "claude-3-5-sonnet", "2026-09-01T12:00:00")
    db = tmp_path / "costs.db"
    runner = CliRunner()
    result = runner.invoke(cli, ["export", "-p", str(log), "--db", str(db)])
    assert result.exit_code == 0
    assert db.exists()

    summary = CostPersistence(db).get_cost_summary()
    assert summary["total_records"] == 1
    assert summary["total_input_tokens"] == 1000
    assert summary["total_output_tokens"] == 500
    assert "Persisted 1 usage record" in result.output


def test_export_json_output(tmp_path: Path):
    log = _claude_log(tmp_path / "logs", "claude-3-5-sonnet", "2026-09-01T12:00:00")
    db = tmp_path / "costs.db"
    runner = CliRunner()
    result = runner.invoke(cli, ["export", "-p", str(log), "--db", str(db), "--json-output"])
    assert result.exit_code == 0
    records = json.loads(result.output)
    assert len(records) == 1
    assert records[0]["model"] == "claude-3-5-sonnet"
    assert records[0]["input_tokens"] == 1000
    assert records[0]["estimated_cost_usd"] > 0
    # --json-output must not touch the database
    assert not db.exists()


def test_export_dry_run_does_not_write(tmp_path: Path):
    log = _claude_log(tmp_path / "logs", "claude-3-5-sonnet", "2026-09-01T12:00:00")
    db = tmp_path / "costs.db"
    runner = CliRunner()
    result = runner.invoke(cli, ["export", "-p", str(log), "--db", str(db), "--dry-run"])
    assert result.exit_code == 0
    assert "Would persist 1 usage record" in result.output
    assert not db.exists()


def test_export_idempotent_skips_existing(tmp_path: Path):
    log = _claude_log(tmp_path / "logs", "claude-3-5-sonnet", "2026-09-01T12:00:00")
    db = tmp_path / "costs.db"
    runner = CliRunner()

    first = runner.invoke(cli, ["export", "-p", str(log), "--db", str(db)])
    assert first.exit_code == 0
    assert "Persisted 1 usage record" in first.output

    second = runner.invoke(cli, ["export", "-p", str(log), "--db", str(db)])
    assert second.exit_code == 0
    assert "skipped 1" in second.output

    # The database still holds exactly one record — the re-run was a no-op.
    assert CostPersistence(db).get_cost_summary()["total_records"] == 1


def test_export_since_until_filters(tmp_path: Path):
    before = _claude_log(tmp_path / "logs", "claude-3-5-sonnet", "2026-08-01T12:00:00")
    inside = _claude_log(tmp_path / "logs", "gpt-4o-mini", "2026-09-01T12:00:00")
    after = _claude_log(tmp_path / "logs", "claude-3-haiku", "2026-10-01T12:00:00")
    db = tmp_path / "costs.db"
    runner = CliRunner()

    result = runner.invoke(cli, [
        "export",
        "-p", str(before), "-p", str(inside), "-p", str(after),
        "--since", "2026-09-01", "--until", "2026-09-30",
        "--db", str(db),
    ])
    assert result.exit_code == 0
    # Only the September entry is in range.
    assert CostPersistence(db).get_cost_summary()["total_records"] == 1
    breakdown = CostPersistence(db).get_model_breakdown()
    assert breakdown[0]["model"] == "gpt-4o-mini"


def test_export_no_data_message(tmp_path: Path):
    db = tmp_path / "costs.db"
    runner = CliRunner()
    # A directory with no logs and --agent forces an empty discovery pass.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    result = runner.invoke(cli, ["export", "-p", str(empty_dir), "--db", str(db)])
    assert result.exit_code == 0
    assert "No usage data found to export" in result.output
    assert not db.exists()
