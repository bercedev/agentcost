"""Tests for agentcost."""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile

from agentcost.cost import TokenUsage, CostBreakdown, calculate_cost, summarize_usage, MODEL_PRICING, is_free_model
from agentcost.parsers import ClaudeCodeParser, CodexParser, HermesParser, OpenCodeParser
from agentcost.discovery import LogDiscovery
from agentcost.report import ReportGenerator


class TestCostCalculation:
    """Calculate cost from token usage."""

    def test_calculate_cost_sonnet(self):
        usage = TokenUsage(
            model="claude-3-5-sonnet",
            input_tokens=10000,
            output_tokens=5000,
        )
        cost = calculate_cost(usage)
        expected = (10000/1e6 * 3.0) + (5000/1e6 * 15.0)
        assert abs(cost - expected) < 0.001

    def test_calculate_cost_with_cache(self):
        usage = TokenUsage(
            model="claude-3-5-sonnet",
            input_tokens=10000,
            output_tokens=5000,
            cache_read_tokens=8000,
            cache_write_tokens=2000,
        )
        cost = calculate_cost(usage)
        expected = (10000/1e6 * 3.0) + (5000/1e6 * 15.0) + (8000/1e6 * 0.3) + (2000/1e6 * 3.75)
        assert abs(cost - expected) < 0.001

    def test_calculate_cost_unknown_model(self):
        usage = TokenUsage(
            model="unknown-model-xyz",
            input_tokens=10000,
            output_tokens=5000,
        )
        cost = calculate_cost(usage)
        # Should use default pricing
        assert cost > 0

    def test_calculate_cost_grok2(self):
        usage = TokenUsage(model="grok-2", input_tokens=10000, output_tokens=5000)
        cost = calculate_cost(usage)
        expected = (10000 / 1e6 * 2.0) + (5000 / 1e6 * 10.0)
        assert abs(cost - expected) < 0.001

    def test_calculate_cost_qwen_max(self):
        usage = TokenUsage(model="qwen-max", input_tokens=10000, output_tokens=5000)
        cost = calculate_cost(usage)
        expected = (10000 / 1e6 * 2.0) + (5000 / 1e6 * 6.0)
        assert abs(cost - expected) < 0.001

    def test_calculate_cost_kimi_latest(self):
        usage = TokenUsage(model="kimi-latest", input_tokens=10000, output_tokens=5000)
        cost = calculate_cost(usage)
        expected = (10000 / 1e6 * 0.21) + (5000 / 1e6 * 2.52)
        assert abs(cost - expected) < 0.001

    def test_calculate_cost_llama_31_405b(self):
        usage = TokenUsage(model="llama-3.1-405b", input_tokens=10000, output_tokens=5000)
        cost = calculate_cost(usage)
        expected = (10000 / 1e6 * 3.0) + (5000 / 1e6 * 15.0)
        assert abs(cost - expected) < 0.001

    def test_calculate_cost_claude_3_7_sonnet(self):
        usage = TokenUsage(model="claude-3-7-sonnet", input_tokens=10000, output_tokens=5000)
        cost = calculate_cost(usage)
        expected = (10000 / 1e6 * 3.0) + (5000 / 1e6 * 15.0)
        assert abs(cost - expected) < 0.001

    def test_calculate_cost_deepseek_r1(self):
        usage = TokenUsage(model="deepseek-r1", input_tokens=10000, output_tokens=5000)
        cost = calculate_cost(usage)
        expected = (10000 / 1e6 * 0.55) + (5000 / 1e6 * 2.19)
        assert abs(cost - expected) < 0.001

    def test_free_models_have_zero_pricing(self):
        for model in (
            "omni-1",
            "muse-spark-1.2-contributor",
        ):
            assert is_free_model(model)
            assert calculate_cost(TokenUsage(model, 1_000_000, 1_000_000)) == 0.0

        assert all(is_free_model(model) for model in MODEL_PRICING if ":free" in model)

    def test_summarize_usage(self):
        usages = [
            TokenUsage("claude-3-5-sonnet", 1000, 500),
            TokenUsage("claude-3-5-sonnet", 2000, 1000),
            TokenUsage("gpt-4o", 500, 250),
        ]
        summary = summarize_usage(usages)
        assert summary.calls == 3
        assert summary.total_input == 3500
        assert summary.total_output == 1750
        assert summary.total_tokens == 5250
        assert summary.total_cost_usd > 0


class TestClaudeCodeParser:
    """Parse Claude Code JSONL logs."""

    def test_parse_basic_jsonl(self, tmp_path):
        """Parse a basic Claude Code JSONL file."""
        log_file = tmp_path / "session.jsonl"
        log_file.write_text(
            '{"type":"assistant","message":{"model":"claude-3-5-sonnet-20241022","usage":{"input_tokens":1000,"output_tokens":500}},"timestamp":"2026-09-11T10:00:00"}\n'
        )
        parser = ClaudeCodeParser()
        usages = parser.parse(log_file)
        assert len(usages) == 1
        assert usages[0].input_tokens == 1000
        assert usages[0].output_tokens == 500
        assert "sonnet" in usages[0].model

    def test_parse_with_cache_write(self, tmp_path):
        """Parse Claude Code entry with cache write tokens."""
        log_file = tmp_path / "session.jsonl"
        log_file.write_text(
            json.dumps({
                "type": "assistant",
                "message": {
                    "model": "claude-3-5-sonnet",
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 500,
                        "cache_read_input_tokens": 200,
                        "cache_creation_input_tokens": 300,
                    },
                },
                "timestamp": "2026-09-11T10:00:00",
            }) + "\n"
        )
        parser = ClaudeCodeParser()
        usages = parser.parse(log_file)
        assert len(usages) == 1
        assert usages[0].cache_write_tokens == 300
        breakdown = summarize_usage(usages)
        assert breakdown.total_cache_write == 300

    def test_parse_multiple_entries(self, tmp_path):
        """Parse multiple JSONL entries."""
        log_file = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type":"assistant","message":{"model":"claude-3-5-sonnet","usage":{"input_tokens":100,"output_tokens":50}}}),
            json.dumps({"type":"assistant","message":{"model":"claude-3-opus","usage":{"input_tokens":200,"output_tokens":100}}}),
        ]
        log_file.write_text("\n".join(lines))
        parser = ClaudeCodeParser()
        usages = parser.parse(log_file)
        assert len(usages) == 2

    def test_parse_skips_invalid_lines(self, tmp_path):
        """Skip invalid JSON lines gracefully."""
        log_file = tmp_path / "session.jsonl"
        log_file.write_text(
            '{"type":"assistant","message":{"model":"claude-3-5-sonnet","usage":{"input_tokens":100,"output_tokens":50}}}\n'
            'this is not json\n'
            '{"type":"assistant","message":{"model":"claude-3-5-sonnet","usage":{"input_tokens":200,"output_tokens":100}}}\n'
        )
        parser = ClaudeCodeParser()
        usages = parser.parse(log_file)
        assert len(usages) == 2

    def test_parse_empty_file(self, tmp_path):
        """Handle empty log file."""
        log_file = tmp_path / "empty.jsonl"
        log_file.write_text("")
        parser = ClaudeCodeParser()
        usages = parser.parse(log_file)
        assert len(usages) == 0


class TestCodexParser:
    """Parse Codex CLI logs."""

    def test_parse_codex_jsonl(self, tmp_path):
        log_file = tmp_path / "codex.jsonl"
        log_file.write_text(
            json.dumps({"model":"gpt-4o","usage":{"input_tokens":500,"output_tokens":200},"timestamp":"2026-09-11T10:00:00"}) + "\n"
        )
        parser = CodexParser()
        usages = parser.parse(log_file)
        assert len(usages) == 1
        assert usages[0].input_tokens == 500

    def test_parse_codex_with_cache_write(self, tmp_path):
        log_file = tmp_path / "codex.jsonl"
        log_file.write_text(
            json.dumps({
                "model": "gpt-4o",
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 200,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 300,
                },
                "timestamp": "2026-09-11T10:00:00",
            }) + "\n"
        )
        parser = CodexParser()
        usages = parser.parse(log_file)
        assert len(usages) == 1
        assert usages[0].cache_write_tokens == 300
        breakdown = summarize_usage(usages)
        assert breakdown.total_cache_write == 300


class TestHermesParser:
    """Parse Hermes agent logs."""

    def test_parse_hermes_tokens_subobject(self, tmp_path):
        log_file = tmp_path / "hermes.jsonl"
        log_file.write_text(
            json.dumps({
                "type": "message",
                "role": "assistant",
                "model": "claude-3-5-sonnet",
                "tokens": {
                    "input_tokens": 1000,
                    "output_tokens": 400,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 500,
                },
                "timestamp": "2026-09-11T10:00:00",
            }) + "\n"
        )
        parser = HermesParser()
        usages = parser.parse(log_file)
        assert len(usages) == 1
        assert usages[0].cache_write_tokens == 500
        breakdown = summarize_usage(usages)
        assert breakdown.total_cache_write == 500

    def test_parse_hermes_usage_subobject(self, tmp_path):
        log_file = tmp_path / "hermes.jsonl"
        log_file.write_text(
            json.dumps({
                "type": "message",
                "role": "assistant",
                "model": "claude-3-5-sonnet",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 400,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 250,
                },
                "timestamp": "2026-09-11T10:00:00",
            }) + "\n"
        )
        parser = HermesParser()
        usages = parser.parse(log_file)
        assert len(usages) == 1
        assert usages[0].cache_write_tokens == 250
        breakdown = summarize_usage(usages)
        assert breakdown.total_cache_write == 250


class TestOpenCodeParser:
    """Parse OpenCode CLI logs."""

    def test_parse_opencode_with_cache_write(self, tmp_path):
        log_file = tmp_path / "opencode.jsonl"
        log_file.write_text(
            json.dumps({
                "model": "claude-3-5-sonnet",
                "usage": {
                    "input_tokens": 800,
                    "output_tokens": 300,
                    "cache_read_input_tokens": 150,
                    "cache_creation_input_tokens": 450,
                },
                "timestamp": "2026-09-11T10:00:00",
            }) + "\n"
        )
        parser = OpenCodeParser()
        usages = parser.parse(log_file)
        assert len(usages) == 1
        assert usages[0].cache_write_tokens == 450
        breakdown = summarize_usage(usages)
        assert breakdown.total_cache_write == 450


class TestLogDiscovery:
    """Discover agent log files."""

    def test_discover_finds_paths(self):
        discovery = LogDiscovery()
        assert len(discovery.paths) > 0

    def test_discover_nonexistent_path(self):
        discovery = LogDiscovery(additional_paths=["/nonexistent/path/xyz"])
        # Should not raise
        logs = discovery.discover()
        assert isinstance(logs, dict)

    def test_discover_classifies_hermes_paths(self, tmp_path):
        logs_dir = tmp_path / ".hermes" / "logs"
        cron_dir = tmp_path / ".hermes" / "cron" / "output"
        logs_dir.mkdir(parents=True)
        cron_dir.mkdir(parents=True)
        session = logs_dir / "session.jsonl"
        cron = cron_dir / "job.json"
        session.write_text("{}")
        cron.write_text("{}")

        logs = LogDiscovery([str(logs_dir), str(cron_dir)]).discover()

        assert session in logs["hermes"]
        assert cron in logs["hermes_cron"]


class TestReportGenerator:
    """Generate cost reports."""

    def test_daily_summary(self):
        now = datetime.now()
        usages = [
            TokenUsage("claude-3-5-sonnet", 1000, 500, timestamp=now),
            TokenUsage("claude-3-5-sonnet", 2000, 1000, timestamp=now),
        ]
        gen = ReportGenerator()
        report = gen.daily_summary(usages, now)
        assert report["total_calls"] == 2
        assert report["total_tokens"] == 4500

    def test_monthly_summary(self):
        now = datetime.now()
        usages = [
            TokenUsage("claude-3-5-sonnet", 5000, 2000, timestamp=now),
        ]
        gen = ReportGenerator()
        report = gen.monthly_summary(usages, now)
        assert report["total_calls"] == 1
        assert report["total_tokens"] == 7000

    def test_projection(self):
        now = datetime.now()
        usages = [
            TokenUsage("claude-3-5-sonnet", 10000, 5000, timestamp=now),
        ]
        gen = ReportGenerator()
        projection = gen.projection(usages)
        assert projection["projected_monthly_usd"] > 0
        assert "daily_average_usd" in projection

    def test_summaries_accept_naive_and_aware_timestamps(self):
        date = datetime(2026, 1, 15, 12)
        usages = [
            TokenUsage("gpt-4o", 100, 50, timestamp=date),
            TokenUsage("gpt-4o", 100, 50, timestamp=date.replace(tzinfo=timezone.utc)),
        ]
        gen = ReportGenerator()

        assert gen.daily_summary(usages, date)["total_calls"] == 2
        assert gen.weekly_summary(usages, date)["total_calls"] == 2
        assert gen.monthly_summary(usages, date)["total_calls"] == 2

    def test_projection_uses_latest_data_timestamp(self):
        first = datetime(2020, 1, 1, tzinfo=timezone.utc)
        usages = [
            TokenUsage("gpt-4o", 1_000, 500, timestamp=first),
            TokenUsage("gpt-4o", 1_000, 500, timestamp=first + timedelta(days=7)),
        ]
        gen = ReportGenerator()

        projection = gen.projection(usages)

        assert projection["days_of_data"] == 7
        assert projection == gen.projection(usages)

    def test_empty_usages(self):
        gen = ReportGenerator()
        report = gen.daily_summary([])
        assert report["total_calls"] == 0
        assert report["total_tokens"] == 0


class TestTokenUsage:
    """TokenUsage dataclass."""

    def test_total_tokens(self):
        usage = TokenUsage(
            model="claude-3-5-sonnet",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            cache_write_tokens=100,
        )
        assert usage.total_tokens == 1800

    def test_timestamp_is_normalized_to_utc(self):
        usage = TokenUsage("gpt-4o", 1, 1, timestamp=datetime(2026, 1, 1))
        assert usage.timestamp.tzinfo is timezone.utc
