"""The composite action's alert argv must emit machine-readable output."""

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from agentcost.cli import cli
from agentcost.cost import TokenUsage, calculate_cost

cli_module = importlib.import_module("agentcost.cli")


@pytest.mark.parametrize("threshold_factor,expected_exit", [(2, 0), (1, 0), (0.5, 1)])
@pytest.mark.parametrize("quiet", [False, True])
def test_alert_action_json_argv(monkeypatch, tmp_path, threshold_factor, expected_exit, quiet):
    usage = TokenUsage("claude-3-5-sonnet", 1000, 500, timestamp=datetime.now(timezone.utc))
    yesterday = TokenUsage("claude-3-5-sonnet", 1000000, 500000,
                           timestamp=datetime.now(timezone.utc) - timedelta(days=2))
    def parse(paths, agent=None):
        assert paths == [tmp_path]
        return [usage, yesterday]
    monkeypatch.setattr(cli_module, "_parse_all_logs", parse)
    threshold = calculate_cost(usage) * threshold_factor
    # Keep the same argument order and option names as action.yml.
    argv = ["alert", "--path", str(tmp_path), "--threshold", str(threshold), "--json-output"]
    if quiet:
        argv.append("--quiet")
    result = CliRunner().invoke(cli, argv)
    assert result.exit_code == expected_exit, result.output
    assert result.stderr == ""
    data = json.loads(result.stdout)
    assert data == {
        "calls": 1, "total_tokens": 1500, "input_tokens": 1000,
        "output_tokens": 500, "cache_read_tokens": 0, "cache_write_tokens": 0,
        "total_cost_usd": round(calculate_cost(usage), 4),
    }
    action = (Path(__file__).resolve().parents[1] / "action.yml").read_text()
    assert 'agentcost alert --path "$ROOT" --threshold "$THRESHOLD" --json-output' in action


def test_alert_json_empty_input(monkeypatch):
    monkeypatch.setattr(cli_module, "_parse_all_logs", lambda *a, **k: [])
    result = CliRunner().invoke(cli, ["alert", "--json-output"])
    assert result.exit_code == 0, result.output
    assert all(value == 0 for value in json.loads(result.stdout).values())


def test_alert_json_does_not_hide_invalid_threshold(monkeypatch):
    def unexpected_parse(*args, **kwargs):
        pytest.fail("invalid threshold must be rejected before reading logs")
    monkeypatch.setattr(cli_module, "_parse_all_logs", unexpected_parse)
    result = CliRunner().invoke(cli, ["alert", "--json-output", "--threshold", "-1"])
    assert result.exit_code == 2
    assert "--threshold" in result.output
    assert "No such option" not in result.output


def test_alert_sarif_takes_precedence_over_json(monkeypatch):
    monkeypatch.setattr(cli_module, "_parse_all_logs", lambda *a, **k: [])
    result = CliRunner().invoke(cli, ["alert", "--sarif", "--json-output"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["version"] == "2.1.0"
    assert "runs" in data
    assert "total_cost_usd" not in data
