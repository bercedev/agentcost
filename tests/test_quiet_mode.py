"""Tests for --quiet / -q flag across all commands."""

import json
from datetime import datetime
from pathlib import Path
from click.testing import CliRunner
import pytest

from agentcost.cli import cli
from agentcost.budget import load_budget_config


@pytest.fixture
def sample_claude_log(tmp_path: Path) -> Path:
    """Create a sample claude jsonl log with current timestamp."""
    log_dir = tmp_path / "claude_logs"
    log_dir.mkdir()
    log_file = log_dir / "claude_session.jsonl"
    entry = {
        "type": "assistant",
        "timestamp": datetime.now().isoformat(),
        "message": {
            "model": "claude-3-5-sonnet",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        },
    }
    log_file.write_text(json.dumps(entry) + "\n")
    return log_file


def test_discover_quiet(sample_claude_log: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", "-p", str(sample_claude_log.parent), "--quiet"])
    assert result.exit_code == 0
    # Should only contain paths, no rich headers
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    assert "Hermes SQLite database" not in result.output
    assert "Found log files" not in result.output
    assert str(sample_claude_log) in lines


def test_today_quiet(sample_claude_log: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["today", "-p", str(sample_claude_log), "--quiet"])
    assert result.exit_code == 0
    # Output should be valid JSON and have no rich borders/panels
    assert "agentcost — Today" not in result.output
    data = json.loads(result.output)
    assert "calls" in data
    assert "total_tokens" in data
    assert "total_cost_usd" in data


def test_today_quiet_and_json_output(sample_claude_log: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["today", "-p", str(sample_claude_log), "--json-output", "-q"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["calls"] == 1
    assert data["total_tokens"] == 1500


def test_week_quiet(sample_claude_log: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["week", "-p", str(sample_claude_log), "--days", "7", "-q"])
    assert result.exit_code == 0
    assert "agentcost — 7 Days" not in result.output
    data = json.loads(result.output)
    assert len(data) > 0


def test_alert_quiet_under_threshold(sample_claude_log: Path):
    runner = CliRunner()
    # High threshold => exit 0, no output in quiet mode
    result = runner.invoke(cli, ["alert", "-p", str(sample_claude_log), "--threshold", "100.0", "-q"])
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_alert_quiet_over_threshold(sample_claude_log: Path):
    runner = CliRunner()
    # A positive threshold below the fixture's cost still triggers an alert.
    result = runner.invoke(cli, ["alert", "-p", str(sample_claude_log), "--threshold", "0.000001", "-q"])
    assert result.exit_code == 1
    assert "ALERT: Today's spending" not in result.output


def test_cron_quiet():
    runner = CliRunner()
    result = runner.invoke(cli, ["cron", "-q"])
    assert result.exit_code == 0
    assert "No cron outputs found" not in result.output


def test_analyze_quiet(sample_claude_log: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", str(sample_claude_log), "--agent", "claude", "-q"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "total_cost" in data or "calls" in data or "by_model" in data


def test_compare_quiet(sample_claude_log: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["compare", "-p", str(sample_claude_log), "-q"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.parametrize("quiet_flag", ["--quiet", "-q"])
@pytest.mark.parametrize("thresholds", [
    {"daily": 5.0},
    {"daily": 5.0, "weekly": 25.0, "monthly": 100.0},
])
def test_budget_set_quiet(tmp_path, monkeypatch, quiet_flag, thresholds):
    monkeypatch.setattr("agentcost.budget.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentcost.budget.CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    args = ["budget", "set"]
    for period, amount in thresholds.items():
        args.extend([f"--{period}", str(amount)])

    normal = runner.invoke(cli, args)
    assert normal.exit_code == 0
    assert "Budget thresholds saved" in normal.output
    for period, amount in thresholds.items():
        assert f"{period.title()}: ${amount:.2f}" in normal.output
    expected_config = (tmp_path / "config.toml").read_bytes()
    (tmp_path / "config.toml").unlink()

    quiet = runner.invoke(cli, args + [quiet_flag])
    assert quiet.exit_code == normal.exit_code
    assert quiet.output == ""
    assert (tmp_path / "config.toml").read_bytes() == expected_config
    assert load_budget_config() == thresholds


@pytest.mark.parametrize("quiet_flag", ["--quiet", "-q"])
def test_init_quiet(tmp_path, monkeypatch, quiet_flag):
    monkeypatch.setattr("agentcost.budget.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentcost.budget.CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    normal = runner.invoke(cli, ["init", "--project"], input="1\n2\n3\n")
    assert normal.exit_code == 0
    assert "agentcost — Initialization" in normal.output
    assert "Config saved to" in normal.output
    expected_config = (tmp_path / ".agentcost.toml").read_bytes()
    (tmp_path / ".agentcost.toml").unlink()

    quiet = runner.invoke(cli, ["init", "--project", quiet_flag], input="1\n2\n3\n")
    assert quiet.exit_code == 0
    # only the prompts remain: no banner and no summary
    assert "agentcost — Initialization" not in quiet.output
    assert "Config saved to" not in quiet.output
    assert "Daily: $1.00" not in quiet.output
    assert "Daily budget (USD)" in quiet.output
    assert (tmp_path / ".agentcost.toml").read_bytes() == expected_config


def test_init_quiet_still_reports_an_invalid_number(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["init", "--project", "--quiet"], input="abc\n2\n3\n")
    assert result.exit_code == 1
    assert "Invalid number format" in result.output
    assert not (tmp_path / ".agentcost.toml").exists()
