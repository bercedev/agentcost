"""Tests for the discover command's --agent choice list (#90)."""

import json

from click.testing import CliRunner

from agentcost.cli import cli


def _cursor_log_dir(tmp_path):
    """Create a fixture Cursor log directory with one session file."""
    cursor_dir = tmp_path / "cursor-sessions"
    cursor_dir.mkdir()
    entry = {
        "type": "assistant",
        "timestamp": "2026-10-03T12:00:00Z",
        "message": {
            "model": "gpt-4o",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    }
    (cursor_dir / "session1.jsonl").write_text(json.dumps(entry) + "\n")
    return cursor_dir


def test_discover_agent_cursor(tmp_path):
    """`discover --agent cursor` accepts cursor and finds Cursor logs."""
    cursor_dir = _cursor_log_dir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", "--agent", "cursor", "-p", str(cursor_dir)])
    assert result.exit_code == 0
    assert "cursor" in result.output.lower()


def test_discover_help_lists_cursor(tmp_path):
    """The discover --agent help text lists cursor as a valid choice."""
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", "--help"])
    assert result.exit_code == 0
    assert "cursor" in result.output


def test_discover_reports_unsupported_hermes_cron(tmp_path, monkeypatch):
    cron = tmp_path / "job.json"
    cron.write_text("{}")

    class FakeDiscovery:
        def __init__(self, *_args, **_kwargs):
            pass

        def discover(self):
            return {"hermes_cron": [cron]}

    monkeypatch.setattr("agentcost.cli.LogDiscovery", FakeDiscovery)
    monkeypatch.setattr("agentcost.cli.HermesSQLiteParser.parse", lambda _self: [])

    result = CliRunner().invoke(cli, ["discover"])

    assert result.exit_code == 0
    assert "Hermes cron output: skipped (unsupported format)" in result.output


def test_discover_cursor_dir_under_hermes_path(tmp_path):
    """A cursor dir nested under a .hermes path must classify as cursor.

    Regression: LogDiscovery checked '.hermes' in path_parts before
    'cursor' in base_name, so pytest's TMPDIR (/root/.hermes/cache/scratch)
    made the fixture classify as hermes and --agent cursor hid it.
    """
    base = tmp_path / ".hermes" / "cache"
    base.mkdir(parents=True)
    cursor_dir = base / "cursor-sessions"
    cursor_dir.mkdir()
    (cursor_dir / "session1.jsonl").write_text(json.dumps({
        "type": "assistant",
        "timestamp": "2026-10-03T12:00:00Z",
        "message": {"model": "gpt-4o", "usage": {"input_tokens": 100, "output_tokens": 50}},
    }) + "\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", "--agent", "cursor", "-p", str(cursor_dir)])
    assert result.exit_code == 0
    assert "Found log files" in result.output
    assert "cursor" in result.output.lower()
