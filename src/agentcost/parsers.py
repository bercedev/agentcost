"""Parsers for various AI agent log formats."""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from agentcost.cost import TokenUsage
from agentcost._io import _read_lines_with_fallback
import logging
import math

logger = logging.getLogger(__name__)


def _validate_token_count(value: Any, field_name: str) -> int:
    """Validate and return a non-negative integer token count.

    Returns 0 for invalid values (None, non-numeric, negative, non-finite).
    Logs a warning when an invalid value is encountered.
    """
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        logger.warning("Invalid %s value: %r (non-numeric), using 0", field_name, value)
        return 0
    if not math.isfinite(value):
        logger.warning("Invalid %s value: %r (non-finite), using 0", field_name, value)
        return 0
    if value < 0:
        logger.warning("Invalid %s value: %r (negative), using 0", field_name, value)
        return 0
    return int(value)


class ClaudeCodeParser:
    """Parse Claude Code JSONL log format."""

    def parse(self, log_path: Path) -> List[TokenUsage]:
        """Parse a Claude Code JSONL file."""
        usages = []
        try:
            result = _read_lines_with_fallback(log_path)
            if result.warning:
                logger.warning(result.warning)
            for line in result.lines:
                try:
                    entry = json.loads(line.strip())
                    usage = self._parse_entry(entry)
                    if usage:
                        usages.append(usage)
                except json.JSONDecodeError:
                    continue
        except FileNotFoundError:
            pass
        return usages

    def _parse_entry(self, entry: Dict[str, Any]) -> Optional[TokenUsage]:
        """Parse a single log entry."""
        message = entry.get("message", {})
        usage_data = message.get("usage", {})
        
        if not usage_data:
            return None
        
        # Extract model. `split(":")[-1]` used to keep the tier and throw the
        # model away ("meituan/longcat-2.5-preview:free" -> "free"), which both
        # lost the real name and billed a free tier (#206). _normalize_model_name
        # strips the tier and any provider prefix in one place.
        model = message.get("model", "unknown")
        
        model = self._normalize_model(model)
        
        ts_str = entry.get("timestamp", "")
        timestamp = None
        if ts_str:
            try:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                pass
        
        session_id = entry.get("sessionId", None) or entry.get("session_id")
        
        return TokenUsage(
            model=model,
            input_tokens=_validate_token_count(usage_data.get("input_tokens"), "input_tokens"),
            output_tokens=_validate_token_count(usage_data.get("output_tokens"), "output_tokens"),
            cache_read_tokens=_validate_token_count(usage_data.get("cache_read_input_tokens"), "cache_read_input_tokens"),
            cache_write_tokens=_validate_token_count(usage_data.get("cache_creation_input_tokens") or usage_data.get("cache_write_tokens"), "cache_write_tokens"),
            timestamp=timestamp,
            agent_id="claude-code",
            session_id=session_id,
        )

    def _normalize_model(self, model: str) -> str:
        """Map a logged model name onto its pricing key.

        Only genuine version aliases are rewritten (``claude-sonnet-4-5`` ->
        ``claude-sonnet-4``). Everything else is returned unchanged, because
        MODEL_PRICING already holds exact keys for ``claude-3-7-sonnet``,
        ``gpt-4o``, ``gemini-2.5-pro`` and friends; guessing a family here only
        shadowed the correct row. An earlier version returned its own lowercased,
        separator-mangled form for anything it did not recognise ("gpt-4o" ->
        "gpt 4o"), so no non-Claude model could ever match the table and every
        one of them was silently billed at the fallback rate (#206).
        """
        lowered = model.lower().replace("-", " ").replace(".", " ")
        if "sonnet" in lowered and ("3 5" in lowered or "3.5" in lowered):
            return "claude-3-5-sonnet"
        elif "sonnet" in lowered and "4" in lowered:
            return "claude-sonnet-4"
        elif "opus" in lowered and "4" in lowered:
            return "claude-opus-4"
        return model


class CodexParser:
    """Parse OpenAI Codex CLI log format."""

    def parse(self, log_path: Path) -> List[TokenUsage]:
        """Parse a Codex log file."""
        usages = []
        try:
            result = _read_lines_with_fallback(log_path)
            if result.warning:
                logger.warning(result.warning)
            for line in result.lines:
                try:
                    entry = json.loads(line.strip())
                    usage = self._parse_entry(entry)
                    if usage:
                        usages.append(usage)
                except json.JSONDecodeError:
                    continue
        except FileNotFoundError:
            pass
        return usages

    def _parse_entry(self, entry: Dict[str, Any]) -> Optional[TokenUsage]:
        """Parse a single Codex log entry."""
        usage_data = entry.get("usage", {})
        if not usage_data:
            return None
        
        model = entry.get("model", "gpt-4o")
        if "gpt-4o-mini" in model:
            model = "gpt-4o-mini"
        elif "gpt-4" in model:
            model = "gpt-4o"
        
        ts_str = entry.get("timestamp", "")
        timestamp = None
        if ts_str:
            try:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                pass
        
        return TokenUsage(
            model=model,
            input_tokens=_validate_token_count(usage_data.get("input_tokens"), "input_tokens"),
            output_tokens=_validate_token_count(usage_data.get("output_tokens"), "output_tokens"),
            cache_read_tokens=_validate_token_count(usage_data.get("cache_read_input_tokens"), "cache_read_input_tokens"),
            cache_write_tokens=_validate_token_count(usage_data.get("cache_creation_input_tokens") or usage_data.get("cache_write_tokens"), "cache_write_tokens"),
            timestamp=timestamp,
            agent_id="codex-cli",
            session_id=entry.get("session_id"),
        )


class HermesParser:
    """Parse Hermes agent log format (JSONL from cron output)."""

    def parse(self, log_path: Path) -> List[TokenUsage]:
        """Parse a Hermes log file."""
        usages = []
        try:
            result = _read_lines_with_fallback(log_path)
            if result.warning:
                logger.warning(result.warning)
            for line in result.lines:
                try:
                    entry = json.loads(line.strip())
                    usage = self._parse_entry(entry)
                    if usage:
                        usages.append(usage)
                except json.JSONDecodeError:
                    continue
        except FileNotFoundError:
            pass
        return usages

    def _parse_entry(self, entry: Dict[str, Any]) -> Optional[TokenUsage]:
        """Parse a single Hermes log entry."""
        # Hermes format: {"type":"message","role":"assistant","content":"...","timestamp":"...","model":"...","tokens":{...}}
        usage_data = entry.get("usage", entry.get("tokens", {}))
        if not usage_data:
            return None
        
        model = entry.get("model", "unknown")
        ts_str = entry.get("timestamp", "")
        timestamp = None
        if ts_str:
            try:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                pass
        
        return TokenUsage(
            model=model,
            input_tokens=_validate_token_count(usage_data.get("input_tokens"), "input_tokens"),
            output_tokens=_validate_token_count(usage_data.get("output_tokens"), "output_tokens"),
            cache_read_tokens=_validate_token_count(usage_data.get("cache_read_input_tokens"), "cache_read_input_tokens"),
            cache_write_tokens=_validate_token_count(usage_data.get("cache_creation_input_tokens") or usage_data.get("cache_write_tokens"), "cache_write_tokens"),
            timestamp=timestamp,
            agent_id="hermes-agent",
            session_id=entry.get("session_id"),
        )


class OpenCodeParser:
    """Parse OpenCode CLI log format."""

    def parse(self, log_path: Path) -> List[TokenUsage]:
        """Parse an OpenCode log file."""
        usages = []
        try:
            result = _read_lines_with_fallback(log_path)
            if result.warning:
                logger.warning(result.warning)
            for line in result.lines:
                try:
                    entry = json.loads(line.strip())
                    usage = self._parse_entry(entry)
                    if usage:
                        usages.append(usage)
                except json.JSONDecodeError:
                    continue
        except FileNotFoundError:
            pass
        return usages

    def _parse_entry(self, entry: Dict[str, Any]) -> Optional[TokenUsage]:
        """Parse a single OpenCode log entry."""
        usage_data = entry.get("usage", {})
        if not usage_data:
            return None
        
        model = entry.get("model", "unknown")
        ts_str = entry.get("timestamp", "")
        timestamp = None
        if ts_str:
            try:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                pass
        
        return TokenUsage(
            model=model,
            input_tokens=_validate_token_count(usage_data.get("input_tokens"), "input_tokens"),
            output_tokens=_validate_token_count(usage_data.get("output_tokens"), "output_tokens"),
            cache_read_tokens=_validate_token_count(usage_data.get("cache_read_input_tokens"), "cache_read_input_tokens"),
            cache_write_tokens=_validate_token_count(usage_data.get("cache_creation_input_tokens") or usage_data.get("cache_write_tokens"), "cache_write_tokens"),
            timestamp=timestamp,
            agent_id="opencode-cli",
            session_id=entry.get("session_id"),
        )
