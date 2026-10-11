"""Parser for Cursor AI coding agent logs."""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from agentcost.cost import TokenUsage
from agentcost._io import _read_lines_with_fallback
from agentcost.parsers import _validate_token_count

# Files above this size are skipped with a warning instead of being read (#83).
_MAX_LOG_BYTES = 100 * 1024 * 1024


class CursorParser:
    """Parse Cursor AI coding agent JSONL log format.
    
    Cursor stores session logs in:
    - ~/.cursor/sessions/ (global)
    - .cursor/sessions/ (project-local)
    
    Format: JSONL with entries containing message, usage, model, timestamp.
    """

    def parse(self, log_path: Path, *, strict: bool = False) -> List[TokenUsage]:
        """Parse a Cursor JSONL log file.

        Failures never abort a scan by default: each failed file prints a
        warning to stderr and contributes no usages, so one unreadable log
        cannot mask the rest (#83). With ``strict=True`` the same failures
        raise instead, letting callers exit non-zero.
        """
        try:
            if log_path.stat().st_size > _MAX_LOG_BYTES:
                print(f"Warning: {log_path} exceeds 100MB, skipping", file=sys.stderr)
                return []

            result = _read_lines_with_fallback(log_path)
            if result.warning:
                print(f"Warning: {result.warning}", file=sys.stderr)
                # A log that is not text at all yields no entries under any
                # decoding, so a strict parse must fail rather than report it
                # as an empty session.
                if strict and not result.recoverable:
                    raise ValueError(f"Could not decode {log_path}")

            usages = []
            for line in result.lines:
                try:
                    entry = json.loads(line.strip())
                    usage = self._parse_entry(entry)
                    if usage:
                        usages.append(usage)
                except json.JSONDecodeError:
                    continue
            return usages
        except FileNotFoundError:
            print(f"Warning: {log_path} not found", file=sys.stderr)
            if strict:
                raise
            return []
        except ValueError as e:
            print(f"Warning: Failed to parse {log_path}: {e}", file=sys.stderr)
            if strict:
                raise
            return []

    def _parse_entry(self, entry: Dict[str, Any]) -> Optional[TokenUsage]:
        """Parse a single Cursor log entry."""
        # Cursor wraps the message in a "message" key
        message = entry.get("message", entry)
        usage_data = message.get("usage", {})
        
        if not usage_data:
            return None
        
        # Extract model name. `split(":")[-1]` used to keep the tier and throw
        # the model away ("meituan/longcat-2.5-preview:free" -> "free"), losing
        # the real name and billing a free tier (#206).
        model = message.get("model", entry.get("model", "unknown"))
        model = self._normalize_model(model)
        
        # Parse timestamp
        ts_str = entry.get("timestamp", "")
        timestamp = None
        if ts_str:
            try:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                pass
        
        session_id = entry.get("sessionId") or entry.get("session_id")
        
        return TokenUsage(
            model=model,
            input_tokens=_validate_token_count(usage_data.get("input_tokens"), "input_tokens"),
            output_tokens=_validate_token_count(usage_data.get("output_tokens"), "output_tokens"),
            cache_read_tokens=_validate_token_count(usage_data.get("cache_read_input_tokens"), "cache_read_tokens"),
            cache_write_tokens=_validate_token_count(usage_data.get("cache_creation_input_tokens"), "cache_write_tokens"),
            timestamp=timestamp,
            agent_id="cursor-agent",
            session_id=session_id,
        )

    def _normalize_model(self, model: str) -> str:
        """Map a logged model name onto its pricing key.

        Only genuine version aliases are rewritten (``claude-sonnet-4-5`` ->
        ``claude-sonnet-4``, a spelling MODEL_PRICING does not carry). Anything
        else is returned unchanged: the table already holds exact keys for
        ``claude-3-7-sonnet``, ``gemini-1.5-flash``, ``gpt-4o`` and friends, so
        guessing a family here only shadowed the correct row. An earlier version
        both guessed (``gemini-1.5-flash`` -> ``gemini-2.0-flash``) and returned
        its own lowercased, separator-mangled form for everything it did not
        recognise, which made every non-Claude model unmatchable and silently
        billed at the fallback rate (#206).
        """
        lowered = model.lower().replace("-", " ").replace(".", " ")
        if "sonnet" in lowered:
            if "3 5" in lowered or "3.5" in lowered:
                return "claude-3-5-sonnet"
            elif "4" in lowered:
                return "claude-sonnet-4"
        elif "opus" in lowered:
            if "4" in lowered:
                return "claude-opus-4"
        return model
